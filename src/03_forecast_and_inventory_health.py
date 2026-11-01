"""
Step 3 - Forecast demand (REAL demand), replay inventory (SIMULATED receipts), flag inventory health, export Power BI tables + Excel.

Inputs : data/interim/*.csv (from steps 1-2)
Outputs: data/processed/*.csv (star schema for Power BI) and supply_chain_kpis.xlsx
"""
import numpy as np, pandas as pd
from pathlib import Path
from xgboost import XGBRegressor
from openpyxl.styles import Font

ROOT = Path(__file__).resolve().parents[1]; INT, OUT = ROOT / "data" / "interim", ROOT / "data" / "processed"
OUT.mkdir(exist_ok=True)
HORIZON, TEST = 3, 6
LEAD_DAYS = {"Furniture": 45, "Technology": 35, "Office Supplies": 21}   # must match step 2

d = pd.read_csv(INT / "monthly_demand.csv", parse_dates=["month"])
prod = pd.read_csv(INT / "product_economics.csv")
prod["lead_time_days"] = prod.category.map(LEAD_DAYS)
rec = pd.read_csv(INT / "inventory_receipts_SIMULATED.csv", parse_dates=["receipt_month"])
loc = pd.DataFrame({"loc_id": ["NAM", "LAT", "EUR", "APC", "EMA"], "location": ["North America", "Latin America", "Europe", "APAC", "EMEA & Africa"],
                    "markets": ["US, Canada", "LATAM", "EU", "APAC", "EMEA, Africa"]})
dq = pd.read_csv(INT / "dq_demand.csv")

piv = d.pivot_table(index="month", columns=["product_id", "loc_id"], values="units")
months = list(piv.index); series_ids = list(piv.columns); SNAP = months[-1]
pcode = {s: i for i, s in enumerate(sorted({c[0] for c in series_ids}))}
lcode = {s: i for i, s in enumerate(sorted({c[1] for c in series_ids}))}

# ------------------------------------------------------------ FORECAST (trend-aware pooled XGBoost)
def features(hist, t, pid, lid):
    """Features use only history before month index t, expressed relative to the trailing 12-month average,
    so the model can follow growing or shrinking series instead of memorising absolute levels."""
    h = np.asarray(hist[:t], dtype=float); base = max(h[-12:].mean(), 0.5); r = h / base
    yoy = (h[-3:].mean() + 0.5) / (h[-15:-12].mean() + 0.5)             # last quarter vs same quarter last year
    cal_month = (months[0] + pd.DateOffset(months=t)).month
    return [pcode[pid], lcode[lid], cal_month, r[-1], r[-2], r[-3], r[-12], r[-3:].mean(), r[-6:].mean(), yoy], base
T0 = 15                                                                  # first month with full feature history
def make_model(): return XGBRegressor(n_estimators=250, max_depth=3, learning_rate=0.05, subsample=0.9, colsample_bytree=0.9, random_state=7)
def build_xy(end):
    X, y = [], []
    for pid, lid in series_ids:
        a = piv[(pid, lid)].values.astype(float)
        for t in range(T0, end):
            f, base = features(a, t, pid, lid); X.append(f); y.append(a[t] / base)
    return np.array(X), np.array(y)

cut = len(months) - TEST
bt_model = make_model().fit(*build_xy(cut))
bt = []
for pid, lid in series_ids:
    a = piv[(pid, lid)].values.astype(float)
    for t in range(cut, len(months)):                                    # one-step-ahead using true lags
        f, base = features(a, t, pid, lid)
        bt.append((months[t], pid, lid, a[t], max(float(bt_model.predict(np.array([f]))[0]) * base, 0), a[t - 12], a[t - 3:t].mean()))
bt = pd.DataFrame(bt, columns=["month", "product_id", "loc_id", "actual", "fc_model", "fc_seasonal_naive", "fc_ma3"])
def metrics(df, col):
    a, f = df.actual.values, df[col].values
    return dict(WAPE=np.abs(a - f).sum() / a.sum(), Bias=(f - a).sum() / a.sum())
cmp = pd.DataFrame({m: metrics(bt, c) for m, c in [("XGBoost (trend-aware)", "fc_model"), ("Seasonal naive (same month LY)", "fc_seasonal_naive"),
                                                    ("3-month moving average", "fc_ma3")]}).T
cmp["Forecast accuracy (1-WAPE)"] = 1 - cmp.WAPE
print("Backtest, last 6 months:\n", cmp.round(3))

model = make_model().fit(*build_xy(len(months)))
fut = []
for pid, lid in series_ids:
    work = list(piv[(pid, lid)].values.astype(float))
    for k in range(HORIZON):
        t = len(work); f, base = features(work, t, pid, lid)
        v = max(float(model.predict(np.array([f]))[0]) * base, 0); work.append(v)
        fut.append((months[0] + pd.DateOffset(months=t), pid, lid, np.nan, v))
fut = pd.DataFrame(fut, columns=["month", "product_id", "loc_id", "actual", "fc_model"])

fact_fc = pd.concat([bt.assign(period_type="Backtest")[["month", "product_id", "loc_id", "actual", "fc_model", "fc_seasonal_naive", "period_type"]],
                     fut.assign(fc_seasonal_naive=np.nan, period_type="Future")[["month", "product_id", "loc_id", "actual", "fc_model", "fc_seasonal_naive", "period_type"]]]
                    ).rename(columns={"month": "date", "actual": "actual_units", "fc_model": "forecast_units", "fc_seasonal_naive": "baseline_forecast_units"})
fact_fc[["forecast_units", "baseline_forecast_units"]] = fact_fc[["forecast_units", "baseline_forecast_units"]].round(1)
hist = d[d.month < months[cut]].rename(columns={"month": "date", "units": "actual_units"})[["date", "product_id", "loc_id", "actual_units"]]
hist = hist.assign(forecast_units=np.nan, baseline_forecast_units=np.nan, period_type="History")
pd.concat([hist, fact_fc], ignore_index=True).sort_values(["date", "product_id", "loc_id"]).to_csv(OUT / "fact_demand_forecast.csv", index=False)

# ------------------------------------------------------------ INVENTORY REPLAY (SIMULATED receipts + REAL demand)
cost = dict(zip(prod.product_id, prod.unit_cost_usd)); inv_rows, aging_rows = [], []
for (pid, lid), g in d.groupby(["product_id", "loc_id"]):
    g = g.sort_values("month"); r = rec[(rec.product_id == pid) & (rec.loc_id == lid)].sort_values("receipt_month")
    batches = [[x.receipt_month, x.units_received] for x in r.itertuples() if x.receipt_month < months[0]]
    for row in g.itertuples():
        opening = sum(b[1] for b in batches); recv = int(r[r.receipt_month == row.month].units_received.sum())
        if recv: batches.append([row.month, recv])
        need, sold = row.units, 0
        for b in batches:
            take = min(b[1], need); b[1] -= take; need -= take; sold += take
            if need == 0: break
        batches = [b for b in batches if b[1] > 0]; closing = sum(b[1] for b in batches)
        inv_rows.append((row.month, pid, lid, opening, recv, row.units, sold, row.units - sold, closing, round(closing * cost[pid], 2)))
        if row.month == SNAP:
            for b in batches: aging_rows.append((pid, lid, (SNAP.year - b[0].year) * 12 + SNAP.month - b[0].month, b[1]))
inv = pd.DataFrame(inv_rows, columns=["month_start", "product_id", "loc_id", "opening_units", "receipts_units", "demand_units",
                                      "sales_units", "shortage_units", "closing_units", "closing_value_usd"])
inv.to_csv(OUT / "fact_inventory_monthly.csv", index=False)
ag = pd.DataFrame(aging_rows, columns=["product_id", "loc_id", "age_months", "units"])
ag["age_bucket"] = pd.cut(ag.age_months, [-1, 0, 1, 2, 999], labels=["0-30 days", "31-60 days", "61-90 days", "90+ days"]).astype(str)
ag["value_usd"] = ag.units * ag.product_id.map(cost)
fact_aging = ag.groupby(["product_id", "loc_id", "age_bucket"], as_index=False)[["units", "value_usd"]].sum().round(2)
fact_aging.to_csv(OUT / "fact_inventory_aging.csv", index=False)

# ------------------------------------------------------------ INVENTORY HEALTH SNAPSHOT
lead = dict(zip(prod.product_id, prod.lead_time_days))
snap = inv[inv.month_start == SNAP].copy()
snap = snap.merge(fut.groupby(["product_id", "loc_id"]).fc_model.mean().rename("avg_monthly_forecast").reset_index(), on=["product_id", "loc_id"])
snap = snap.merge(d[d.month > SNAP - pd.DateOffset(months=3)].groupby(["product_id", "loc_id"]).units.mean().rename("avg3_demand").reset_index(), on=["product_id", "loc_id"])
snap["weekly_forecast_demand"] = snap.avg_monthly_forecast / 4.33
snap["weeks_of_supply"] = np.where(snap.weekly_forecast_demand > 0, snap.closing_units / snap.weekly_forecast_demand, np.nan)
snap["lead_time_weeks"] = snap.product_id.map(lead) / 7
snap["safety_stock_units"] = (0.25 * snap.avg3_demand).round()
def status(r):
    if r.closing_units < r.safety_stock_units or r.weeks_of_supply < r.lead_time_weeks: return "Shortage Risk"
    if r.weeks_of_supply > 16: return "Excess"
    return "Healthy"
snap["status"] = snap.apply(status, axis=1)
aged = fact_aging[fact_aging.age_bucket == "90+ days"].groupby(["product_id", "loc_id"])[["units", "value_usd"]].sum()
aged.columns = ["aged_90plus_units", "aged_90plus_value_usd"]
snap = snap.merge(aged, on=["product_id", "loc_id"], how="left").fillna({"aged_90plus_units": 0, "aged_90plus_value_usd": 0})
snap["aged_flag"] = np.where(snap.aged_90plus_units / snap.closing_units.clip(lower=1) > 0.10, "Aged Risk", "OK")
def action(r):
    if r.status == "Shortage Risk":
        need = int(round(max(0, r.lead_time_weeks * r.weekly_forecast_demand + r.safety_stock_units - r.closing_units)))
        return f"Expedite replenishment: about {need} units needed to cover lead time + safety stock"
    if r.status == "Excess": return "Pause new orders and rebalance stock to other hubs"
    if r.aged_flag == "Aged Risk": return "Prioritise aged units for sale or transfer"
    return "Monitor"
snap["recommended_action"] = snap.apply(action, axis=1)
snap = snap.rename(columns={"closing_units": "on_hand_units", "closing_value_usd": "inventory_value_usd"})
snap_out = snap[["product_id", "loc_id", "on_hand_units", "inventory_value_usd", "avg_monthly_forecast", "weekly_forecast_demand", "weeks_of_supply",
                 "lead_time_weeks", "safety_stock_units", "status", "aged_90plus_units", "aged_90plus_value_usd", "aged_flag", "recommended_action"]].round(2)
snap_out.to_csv(OUT / "inventory_health_snapshot.csv", index=False)

# ------------------------------------------------------------ DIMENSIONS
prod.to_csv(OUT / "dim_product.csv", index=False); loc.to_csv(OUT / "dim_location.csv", index=False)
dates = pd.date_range(months[0], SNAP + pd.DateOffset(months=HORIZON), freq="MS")
pd.DataFrame({"date": dates, "year": dates.year, "month_num": dates.month, "month_name": dates.strftime("%b"),
              "quarter": "Q" + dates.quarter.astype(str)}).to_csv(OUT / "dim_date.csv", index=False)

# ------------------------------------------------------------ ACCURACY TABLES + EXCEL
bt2 = bt.merge(prod[["product_id", "category"]], on="product_id").merge(loc[["loc_id", "location"]], on="loc_id")
def acc(df, by):
    g = df.groupby(by).apply(lambda x: pd.Series({"actual_units": x.actual.sum(), "forecast_units": x.fc_model.sum(),
        "forecast_accuracy_pct": 100 * (1 - np.abs(x.actual - x.fc_model).sum() / x.actual.sum()),
        "bias_pct": 100 * (x.fc_model.sum() - x.actual.sum()) / x.actual.sum(),
        "baseline_accuracy_pct": 100 * (1 - np.abs(x.actual - x.fc_seasonal_naive).sum() / x.actual.sum())}), include_groups=False)
    return g.round(1).reset_index()
cmp_out = cmp.round(4).reset_index().rename(columns={"index": "Model"}); cmp_out.to_csv(OUT / "model_comparison.csv", index=False)
h = snap_out.merge(prod[["product_id", "category"]], on="product_id").merge(loc[["loc_id", "location"]], on="loc_id")
M = "XGBoost (trend-aware)"
kpi = pd.DataFrame({"KPI": ["Forecast accuracy, XGBoost (last 6 months)", "Forecast accuracy, seasonal naive baseline", "Forecast accuracy, 3-month moving average",
        "Forecast bias, XGBoost", "Total on-hand units (simulated stock)", "Total inventory value (USD million, simulated)", "Shortage-risk product-hubs",
        "Excess product-hubs", "Aged (90+ day) inventory value (USD million)", "Aged inventory as % of value", "Avg weeks of supply (portfolio)"],
    "Value": [round(100 * (1 - cmp.loc[M, "WAPE"]), 1), round(100 * (1 - cmp.loc["Seasonal naive (same month LY)", "WAPE"]), 1),
        round(100 * (1 - cmp.loc["3-month moving average", "WAPE"]), 1), round(100 * cmp.loc[M, "Bias"], 1), int(h.on_hand_units.sum()),
        round(h.inventory_value_usd.sum() / 1e6, 2), int((h.status == "Shortage Risk").sum()), int((h.status == "Excess").sum()),
        round(h.aged_90plus_value_usd.sum() / 1e6, 2), round(100 * h.aged_90plus_value_usd.sum() / h.inventory_value_usd.sum(), 1),
        round(h.on_hand_units.sum() / h.weekly_forecast_demand.sum(), 1)]})
alerts = h[(h.status != "Healthy") | (h.aged_flag == "Aged Risk")].sort_values(["status", "inventory_value_usd"], ascending=[True, False])
alerts = alerts[["product_id", "category", "location", "status", "on_hand_units", "weeks_of_supply", "lead_time_weeks", "aged_flag", "recommended_action"]]
dq.to_csv(OUT / "data_quality_log.csv", index=False)
with pd.ExcelWriter(ROOT / "supply_chain_kpis.xlsx", engine="openpyxl") as xw:
    for name, df in [("KPI_Summary", kpi), ("Model_Comparison", cmp_out), ("Accuracy_by_Category", acc(bt2, "category")),
                     ("Accuracy_by_Hub", acc(bt2, "location")), ("Accuracy_by_Product", acc(bt2, "product_id")),
                     ("Accuracy_by_Month", acc(bt2.assign(month=bt2.month.dt.strftime("%Y-%m")), "month")),
                     ("Inventory_Health", h), ("Alerts", alerts), ("Data_Quality_Log", dq)]:
        df.to_excel(xw, sheet_name=name, index=False); ws = xw.sheets[name]; ws.freeze_panes = "A2"
        for c in ws[1]: c.font = Font(bold=True)
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(60, max(12, max(len(str(c.value)) if c.value is not None else 0 for c in col[:60]) + 2))
print("\nKPIs:\n", kpi.to_string(index=False)); print("\nStatus:\n", h.status.value_counts().to_string(), "\nAged:\n", h.aged_flag.value_counts().to_string())
print("\nAccuracy by category:\n", acc(bt2, "category").to_string(index=False)); print("\nAccuracy by hub:\n", acc(bt2, "location").to_string(index=False))
