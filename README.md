# Global Supply Chain Demand Forecasting & Inventory Health Analytics

End-to-end analytics project: clean real order data, forecast demand, flag shortage / excess / aged inventory, and present everything in a Power BI dashboard.

## Data: what is real and what is simulated
| Component | Status |
|---|---|
| Orders, quantities, dates, markets, categories, sales and profit | **Real**: public *Global Superstore* sales dataset (51,290 order lines, 2011-2014), available on Kaggle. Copy used: [pplonski/datasets-for-start](https://github.com/pplonski/datasets-for-start). Check the dataset's terms and cite it. |
| Unit price and unit cost | **Derived from the real data** (price = Sales / Quantity, cost = (Sales - Profit) / Quantity, per product group) |
| Product groups and hubs | **Real data, regrouped**: 17 Sub-Categories as products; 7 markets grouped into 5 distribution hubs |
| Inventory receipts, stock levels, aging, lead times, safety stock | **Simulated**. The dataset has no stock data, so replenishment is simulated (see `src/02_simulate_inventory.py`). Some product-hubs are deliberately given supplier delays or a bulk purchase so there is something to analyse. |

The dataset covers 2011-2014, so treat this as a historical case study. State the simulated-inventory limitation in interviews.

## Business questions
1. How accurate is the demand forecast, and where is it biased?
2. What does demand look like over the next three months?
3. Which product-hubs risk a **shortage**, hold **excess**, or carry **aged** (90+ day) stock?
4. What should planners do about each?

## What is in the project
| Layer | Tool | What it does |
|---|---|---|
| Data prep | Python (Pandas) | Parses two mixed date formats, checks integrity, regroups markets into hubs, builds monthly demand for 85 product-hub series; findings in `data_quality_log.csv` |
| Forecasting | Python (XGBoost) | One pooled, trend-aware model (features relative to each series' trailing 12-month average); compared with two baselines |
| Inventory analytics | Python (FIFO replay) | Replays simulated receipts against real demand: monthly stock, lost sales, stock age, weeks of supply, status flags |
| Reporting | Excel (`supply_chain_kpis.xlsx`) | KPI summary, accuracy tables, alerts list for planners |
| Dashboard | **Power BI** (see `docs/powerbi_guide.md`) | Star schema, Power Query cleaning, DAX measures, 4-page dashboard |
| Generative AI | ChatGPT / Copilot | Used to speed up DAX and code (log your real usage in `docs/genai_log.md`) |

## Repository structure
```
src/01_prepare_demand.py                 download + clean real data -> monthly demand
src/02_simulate_inventory.py             SIMULATED receipts and stock policy (assumptions at the top)
src/03_forecast_and_inventory_health.py  forecast, inventory health, Power BI tables, Excel
data/raw/                                dataset is downloaded here (not committed)
data/interim/                            monthly demand, product economics, simulated receipts
data/processed/                          star-schema tables ready for Power BI
supply_chain_kpis.xlsx                   planner-friendly Excel summary
docs/                                    Power BI guide and GenAI log template
```

## How to run
```bash
pip install -r requirements.txt
python src/01_prepare_demand.py
python src/02_simulate_inventory.py
python src/03_forecast_and_inventory_health.py
```

## Method
- **Cleaning:** `Order Date` mixes `dd-mm-yyyy` (31,223 rows) and `m/d/yyyy` (20,067 rows); both are parsed. `Ship Date` could not be parsed into plausible order-to-ship gaps for 24,348 rows, so real lead times could not be measured and lead times are assumed (21-45 days by category). No duplicates or non-positive quantities were found. 51 empty product-hub-months were set to zero demand.
- **Forecast model:** one XGBoost regressor on all 85 series. Features: product, hub, calendar month, last 3 months, same month last year, 3- and 6-month averages, and a year-over-year growth signal; demand is expressed relative to the trailing 12-month average so the model follows growing series.
- **Validation:** hold out the last 6 months (Jul-Dec 2014), predict one month ahead with true lags, and compare with *seasonal naive* and a *3-month moving average*. The final model is retrained on all history to forecast Jan-Mar 2015.
- **Inventory status (Dec 2014 month-end):**
  - *Shortage Risk*: on-hand below safety stock (25% of the last 3 months' demand), or weeks of supply below lead time.
  - *Excess*: more than 16 weeks of forecast demand on hand.
  - *Aged Risk*: more than 10% of on-hand units older than 90 days.

## Results (from the included run)
| Metric | Value |
|---|---|
| Forecast accuracy, XGBoost (last 6 months) | **73.4%** |
| Seasonal naive baseline | 65.6% |
| 3-month moving average baseline | 69.3% |
| Forecast bias, XGBoost | +1.1% |
| Best / worst hub accuracy | Europe 77.9% / EMEA & Africa 67.3% |
| Best / worst category accuracy | Furniture 75.7% / Technology 70.1% |
| Shortage-risk / Excess / Aged-risk product-hubs (simulated stock) | 15 / 14 / 8 of 85 |

**Honest reading:**
- Product-hub demand is lumpy (about 44 units per series per month), so 73% accuracy is reasonable, not exceptional.
- My first version of the model scored only about 68% and under-forecast by 20%, because demand grew roughly 25% a year and the model used absolute levels. Making the features relative to each series' recent average fixed this. It is worth explaining in an interview.
- The inventory results depend entirely on the simulation assumptions and say nothing about the real business.
- The backtest covers only 6 months of one dataset.

## Limitations and next steps
- No real stock or supplier data; lead times are assumptions.
- Add price/discount features (the dataset has a `Discount` column) and prediction intervals.
- Repeat the backtest across several rolling windows.
- Dashboard screenshots: *(add after you build the Power BI report)*
