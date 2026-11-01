"""
Step 1 - Download and clean the REAL Global Superstore sales data, then aggregate to monthly demand.

Source: Global Superstore Sales dataset (2011-2014), publicly available on Kaggle.
        Copy used here: github.com/pplonski/datasets-for-start (superstore-sales/superstore_dataset2011-2015.csv).
        Check the dataset's licence/terms before redistributing; for a portfolio project, cite the source.

Mapping used to make a supply-chain view out of retail orders:
  product            = Sub-Category (17 product groups, 3 categories)
  distribution hub   = Market grouped into 5 hubs (see HUB_MAP)
  demand             = Quantity ordered (units) per month
  unit price / cost  = derived from the real Sales and Profit columns: cost = (Sales - Profit) / Quantity
"""
import urllib.request
import numpy as np, pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW, INT = ROOT / "data" / "raw" / "global_superstore.csv", ROOT / "data" / "interim"
URL = "https://raw.githubusercontent.com/pplonski/datasets-for-start/refs/heads/master/superstore-sales/superstore_dataset2011-2015.csv"
HUB_MAP = {"US": "North America", "Canada": "North America", "LATAM": "Latin America", "EU": "Europe",
           "APAC": "APAC", "EMEA": "EMEA & Africa", "Africa": "EMEA & Africa"}
HUB_CODE = {"North America": "NAM", "Latin America": "LAT", "Europe": "EUR", "APAC": "APC", "EMEA & Africa": "EMA"}

if not RAW.exists():
    print("Downloading dataset ..."); urllib.request.urlretrieve(URL, RAW)
df = pd.read_csv(RAW, encoding="latin1")
dq = [("Raw order lines loaded", len(df), "Each row is one product line on an order")]

# 1) mixed date formats: 'dd-mm-yyyy' and 'm/d/yyyy' appear in the same column
def parse_mixed(s):
    dash = s.str.contains("-")
    a = pd.to_datetime(s.where(dash), format="%d-%m-%Y", errors="coerce")
    b = pd.to_datetime(s.where(~dash), format="%m/%d/%Y", errors="coerce")
    return a.fillna(b), int(dash.sum())
df["order_date"], n_dash = parse_mixed(df["Order Date"])
assert df.order_date.notna().all()
dq.append(("Order Date in dd-mm-yyyy format", n_dash, "Order Date mixes dd-mm-yyyy and m/d/yyyy; both parsed to real dates"))
dq.append(("Order Date in m/d/yyyy format", len(df) - n_dash, "Parsed with the US-style format"))

# 2) Ship Date uses inconsistent conventions -> not reliable, so not used for lead times
ship, _ = parse_mixed(df["Ship Date"]); days = (ship - df.order_date).dt.days
dq.append(("Ship Date not usable for lead time", int((~days.between(0, 10)).sum()),
           "Order-to-ship gap is negative or implausible after parsing; lead times are therefore ASSUMED in this project"))
dq.append(("Postal Code missing", int(df["Postal Code"].isna().sum()), "Column not needed; ignored"))

# 3) integrity checks
dq.append(("Exact duplicate rows", int(df.duplicated().sum()), "None found"))
dq.append(("Quantity <= 0", int((df.Quantity <= 0).sum()), "None found"))
df["hub"] = df.Market.map(HUB_MAP); assert df.hub.notna().all()
dq.append(("Markets grouped into 5 hubs", df.Market.nunique(), "US+Canada, LATAM, EU, APAC, EMEA+Africa to keep series volumes large enough to forecast"))

# 4) monthly demand per product x hub (months without orders are true zeros)
df["month"] = df.order_date.dt.to_period("M").dt.to_timestamp()
grid_months = pd.date_range(df.month.min(), df.month.max(), freq="MS")
demand = df.groupby(["Sub-Category", "hub", "month"]).Quantity.sum()
idx = pd.MultiIndex.from_product([sorted(df["Sub-Category"].unique()), sorted(df.hub.unique()), grid_months], names=["Sub-Category", "hub", "month"])
demand = demand.reindex(idx)
dq.append(("Empty product-hub-months set to 0", int(demand.isna().sum()), "No orders that month = zero demand"))
demand = demand.fillna(0).astype(int).reset_index().rename(columns={"Sub-Category": "product_id", "hub": "hub_name", "Quantity": "units"})
demand["loc_id"] = demand.hub_name.map(HUB_CODE)
demand[["month", "product_id", "loc_id", "units"]].to_csv(INT / "monthly_demand.csv", index=False)
dq.append(("Final monthly series", demand.groupby(["product_id", "loc_id"]).ngroups, f"{len(grid_months)} months each ({grid_months[0]:%b %Y} to {grid_months[-1]:%b %Y})"))

# 5) product economics from real Sales / Profit / Quantity
g = df.groupby(["Category", "Sub-Category"]).agg(sales=("Sales", "sum"), profit=("Profit", "sum"), qty=("Quantity", "sum")).reset_index()
g["unit_price_usd"] = (g.sales / g.qty).round(2); g["unit_cost_usd"] = ((g.sales - g.profit) / g.qty).round(2)
prod = g.rename(columns={"Sub-Category": "product_id", "Category": "category"})[["product_id", "category", "unit_price_usd", "unit_cost_usd"]]
prod.insert(1, "product_name", prod.product_id)
prod.to_csv(INT / "product_economics.csv", index=False)
pd.DataFrame(dq, columns=["Check", "Rows affected", "Treatment"]).to_csv(INT / "dq_demand.csv", index=False)
print(pd.DataFrame(dq, columns=["Check", "Rows affected", "Treatment"]).to_string(index=False))
print(f"\nTotal units: {demand.units.sum():,} | series: {demand.groupby(['product_id','loc_id']).ngroups} | months: {len(grid_months)}")
