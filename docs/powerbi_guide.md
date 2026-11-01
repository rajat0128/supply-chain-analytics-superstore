# Power BI build guide

Data note: demand, prices and costs come from the real Global Superstore dataset; **inventory is simulated**. Say so in the dashboard footer (add a text box: \"Inventory data simulated\").

Goal: turn the files in `data/processed/` into a 4-page dashboard a supply chain planner could use. Budget about 6-8 hours. Do the steps yourself in Power BI Desktop (free, Windows). Use ChatGPT or Copilot to help with DAX, and log what you used in `genai_log.md`.

## 1. Load data
Get Data > Text/CSV. Load these seven files from `data/processed/`:
`dim_product`, `dim_location`, `dim_date`, `fact_demand_forecast`, `fact_inventory_monthly`, `fact_inventory_aging`, `inventory_health_snapshot` (seven tables in total).

### Power Query practice (do this once, for the CV)
The processed files are already clean. To practise Power Query on the **real** raw data, load `data/raw/global_superstore.csv` (Text/CSV, file origin: Western European Latin-1) as a separate query `orders_raw` and rebuild the monthly demand yourself:
1. **Dates:** `Order Date` mixes `dd-mm-yyyy` and `m/d/yyyy`. Add Column > Custom Column `OrderDate`:
```
if Text.Contains([Order Date], "-")
then Date.FromText([Order Date], [Format="dd-MM-yyyy", Culture="en-US"])
else Date.FromText([Order Date], [Format="M/d/yyyy", Culture="en-US"])
```
2. **Month:** Add Column > Custom Column `Month` = `Date.StartOfMonth([OrderDate])`.
3. **Hubs:** Add a conditional column `Hub`: US or Canada -> North America; LATAM -> Latin America; EU -> Europe; APAC -> APAC; EMEA or Africa -> EMEA & Africa (or merge with a small mapping table).
4. **Aggregate:** Home > Group By on `Sub-Category`, `Hub`, `Month`; operation Sum of `Quantity`, named `units`.
5. **Compare** with the History rows of `fact_demand_forecast` (the totals should match) and keep the Applied Steps tidy and named, because you will explain them in interviews.
6. Note what Power Query cannot easily do (the Python model, simulated inventory), and say why you used both tools.

## 2. Data model (Model view)
Star schema. Create these one-to-many relationships (dimension on the "1" side, single direction):

| From (1) | To (many) |
|---|---|
| `dim_product[product_id]` | `fact_demand_forecast[product_id]`, `fact_inventory_monthly[product_id]`, `fact_inventory_aging[product_id]`, `inventory_health_snapshot[product_id]` |
| `dim_location[loc_id]` | same four fact tables on `loc_id` |
| `dim_date[date]` | `fact_demand_forecast[date]`, `fact_inventory_monthly[month_start]` |

Set data types: dates as Date, `inventory_value_usd` as Fixed decimal number. Hide the key columns in the fact tables. Sort `dim_date[month_name]` by `month_num`.

## 3. DAX measures
Create a table called `_Measures` (Home > Enter Data) and add these measures.

```DAX
-- Demand & forecast
Actual Demand = SUM ( fact_demand_forecast[actual_units] )
Forecast Units = SUM ( fact_demand_forecast[forecast_units] )

Backtest Actual =
CALCULATE ( [Actual Demand], fact_demand_forecast[period_type] = "Backtest" )

Backtest Abs Error =
CALCULATE (
    SUMX ( fact_demand_forecast,
           ABS ( fact_demand_forecast[actual_units] - fact_demand_forecast[forecast_units] ) ),
    fact_demand_forecast[period_type] = "Backtest" )

WAPE = DIVIDE ( [Backtest Abs Error], [Backtest Actual] )
Forecast Accuracy % = 1 - [WAPE]

Forecast Bias % =
DIVIDE (
    CALCULATE ( [Forecast Units], fact_demand_forecast[period_type] = "Backtest" ) - [Backtest Actual],
    [Backtest Actual] )

Baseline Accuracy % =
1 - DIVIDE (
    CALCULATE (
        SUMX ( fact_demand_forecast,
               ABS ( fact_demand_forecast[actual_units] - fact_demand_forecast[baseline_forecast_units] ) ),
        fact_demand_forecast[period_type] = "Backtest" ),
    [Backtest Actual] )

Accuracy Gain vs Baseline (pp) = ( [Forecast Accuracy %] - [Baseline Accuracy %] ) * 100

Demand YoY % =
VAR LY =
    CALCULATE ( [Actual Demand], ALL ( dim_date ),
        dim_date[year] = SELECTEDVALUE ( dim_date[year] ) - 1,
        dim_date[month_num] = SELECTEDVALUE ( dim_date[month_num] ) )
RETURN DIVIDE ( [Actual Demand] - LY, LY )

-- Inventory health (latest month-end snapshot)
On-Hand Units = SUM ( inventory_health_snapshot[on_hand_units] )
Inventory Value (USD M) = DIVIDE ( SUM ( inventory_health_snapshot[inventory_value_usd] ), 1000000 )
Weeks of Supply =
DIVIDE ( SUM ( inventory_health_snapshot[on_hand_units] ), SUM ( inventory_health_snapshot[weekly_forecast_demand] ) )

Shortage Risk Count =
CALCULATE ( COUNTROWS ( inventory_health_snapshot ), inventory_health_snapshot[status] = "Shortage Risk" )
Excess Count =
CALCULATE ( COUNTROWS ( inventory_health_snapshot ), inventory_health_snapshot[status] = "Excess" )
Excess Value (USD M) =
DIVIDE ( CALCULATE ( SUM ( inventory_health_snapshot[inventory_value_usd] ),
         inventory_health_snapshot[status] = "Excess" ), 1000000 )

-- Aging
Aged Value (USD M) =
DIVIDE ( CALCULATE ( SUM ( fact_inventory_aging[value_usd] ), fact_inventory_aging[age_bucket] = "90+ days" ), 1000000 )
Aged % =
DIVIDE ( CALCULATE ( SUM ( fact_inventory_aging[value_usd] ), fact_inventory_aging[age_bucket] = "90+ days" ),
         SUM ( fact_inventory_aging[value_usd] ) )

-- Service
Fill Rate % = DIVIDE ( SUM ( fact_inventory_monthly[sales_units] ), SUM ( fact_inventory_monthly[demand_units] ) )
Lost Sales Units = SUM ( fact_inventory_monthly[shortage_units] )

-- Dynamic headline for a text card
Headline =
"Forecast accuracy " & FORMAT ( [Forecast Accuracy %], "0.0%" ) &
" | " & [Shortage Risk Count] & " shortage risks, " & [Excess Count] & " excess positions" &
" | Aged stock " & FORMAT ( [Aged %], "0.0%" ) & " of inventory value"
```

## 4. Dashboard pages
Add slicers for **Category**, **Hub (location)** and **Year** on every page (Sync slicers across pages). Use one colour per status: red = Shortage Risk, amber = Excess, green = Healthy.

| Page | Visuals |
|---|---|
| **1. Executive Overview** | Headline text card; KPI cards (Forecast Accuracy %, Forecast Bias %, Inventory Value, Weeks of Supply, Shortage Risk Count, Aged %); stacked bar of status count by hub; line chart of demand by month |
| **2. Demand & Forecast** | Line chart: Actual Demand vs Forecast Units by month (colour future months differently); clustered column of Forecast Accuracy % vs Baseline Accuracy % by category; matrix of accuracy and bias by product with conditional formatting; YoY % card |
| **3. Inventory Health** | Weeks of Supply by product (bar, with a reference line at 16 weeks); donut of aged inventory by `age_bucket`; scatter of on-hand units vs weekly forecast demand (size = value); treemap of Excess Value by category |
| **4. Planner Actions** | Table from `inventory_health_snapshot`: product, hub, status, on-hand, weeks of supply, lead time weeks, `recommended_action`; filter to Shortage Risk and Excess; add a drill-through page from Page 1 |

Tips: use consistent fonts and alignment, keep 5-6 visuals per page, add a title and a one-line "so what" under each chart, and use bookmarks for a "Shortage view" and an "Excess view".

## 5. Publish and document
- Save as `supply_chain_dashboard.pbix`, export a PDF, and add 3-4 screenshots to the README.
- Write 5 bullet-point insights from the dashboard (for example, "which categories have the worst forecast bias and why").
- Practise a 2-minute walkthrough: problem, data, method, three findings, what you would do next.

## 6. How this maps to the job description
| JD requirement | Where it is covered |
|---|---|
| Power BI dashboards and KPIs | Sections 2-4 of this guide |
| Demand planning and forecast analytics (accuracy, trends, demand patterns) | Forecast model, WAPE / bias, Page 2 |
| Supply and inventory analytics (shortages, excess, aged stock) | FIFO replay, status flags, Pages 3-4 |
| Python, automation and AI | `src/` scripts regenerate everything with one command; generative AI log |
| Data manipulation, SQL, Power Query, DAX, Excel | Pandas cleaning, Power Query practice on the raw data, DAX measures, `supply_chain_kpis.xlsx` |
| Communicating insights | Page 1 headline, Page 4 recommended actions, 2-minute walkthrough |
