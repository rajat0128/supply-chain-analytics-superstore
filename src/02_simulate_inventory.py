"""
Step 2 - SIMULATE inventory receipts on top of the REAL demand.

The public dataset has sales but no stock data, so stock levels cannot be observed.
This step creates a plausible replenishment history so inventory analytics can be practised.
EVERYTHING written here is simulated: say so on your CV, README and in interviews.

Assumptions (all editable below):
  - replenishment lead time by category (days)
  - order-up-to policy: stock target = last-3-month average demand x (lead time in months + 1.8)
  - a few product-hub combinations are deliberately given supplier delays (shortage risk)
    or a one-off bulk purchase (excess and aged stock) so the dashboard has something to show
"""
import numpy as np, pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; INT = ROOT / "data" / "interim"
rng = np.random.default_rng(2024)
LEAD_DAYS = {"Furniture": 45, "Technology": 35, "Office Supplies": 21}          # ASSUMED
N_SHORTAGE, N_EXCESS = 6, 6

d = pd.read_csv(INT / "monthly_demand.csv", parse_dates=["month"])
prod = pd.read_csv(INT / "product_economics.csv")
lead = {p: LEAD_DAYS[c] for p, c in zip(prod.product_id, prod.category)}
months = sorted(d.month.unique()); n = len(months)

recent = d[d.month >= months[-3]].groupby(["product_id", "loc_id"]).units.mean()
pool = list(recent[recent >= 40].index)                                        # only meaningful volumes
pick = rng.choice(len(pool), N_SHORTAGE + N_EXCESS, replace=False)
SHORTAGE = {pool[i] for i in pick[:N_SHORTAGE]}; EXCESS = {pool[i] for i in pick[N_SHORTAGE:]}

rows = []
for (pid, lid), g in d.groupby(["product_id", "loc_id"]):
    g = g.sort_values("month").reset_index(drop=True); lt_m = lead[pid] / 30.0
    batches = [[months[0] - pd.DateOffset(months=1), int(max(g.units.iloc[:3].mean() * 1.5, 1))]]
    rows.append((batches[0][0], pid, lid, batches[0][1]))
    for i, r in g.iterrows():
        on_hand = sum(b[1] for b in batches)
        avg3 = g.units.iloc[max(0, i - 3):i].mean() if i > 0 else r.units
        order = max(0.0, avg3 * (lt_m + 1.8) - on_hand) * rng.uniform(0.9, 1.1)
        if i >= n - 4 and (pid, lid) in SHORTAGE: order *= 0.25                  # supplier delays
        if i == n - 6 and (pid, lid) in EXCESS:   order += avg3 * 9              # bulk buy 5 months ago
        order = int(round(order))
        if order > 0: batches.append([r.month, order]); rows.append((r.month, pid, lid, order))
        need = r.units
        for b in batches:                                                        # FIFO consumption
            take = min(b[1], need); b[1] -= take; need -= take
            if need == 0: break
        batches = [b for b in batches if b[1] > 0]
rec = pd.DataFrame(rows, columns=["receipt_month", "product_id", "loc_id", "units_received"])
rec.to_csv(INT / "inventory_receipts_SIMULATED.csv", index=False)
pd.DataFrame([(p, l, "Shortage scenario") for p, l in sorted(SHORTAGE)] + [(p, l, "Excess scenario") for p, l in sorted(EXCESS)],
             columns=["product_id", "loc_id", "seeded_scenario"]).to_csv(INT / "seeded_scenarios.csv", index=False)
print(f"{len(rec)} simulated receipts | seeded shortage: {sorted(SHORTAGE)} | seeded excess: {sorted(EXCESS)}")
