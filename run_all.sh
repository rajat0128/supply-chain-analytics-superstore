#!/usr/bin/env bash
# Downloads the public dataset (if needed) and regenerates every output
set -e
pip install -r requirements.txt
python src/01_prepare_demand.py
python src/02_simulate_inventory.py
python src/03_forecast_and_inventory_health.py
