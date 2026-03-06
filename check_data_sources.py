import logging
import pandas as pd
from options_manager import OptionsManager
from stocko_auth import StockoAuth
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def run_diagnostics():
    print("=== DATA SOURCE DIAGNOSTICS ===")

    # 1. Test Stocko API
    print("\n[1/3] Testing Stocko API...")
    auth = StockoAuth()
    if not auth._load_cached_token():
        print("  - ERROR: No cached token found. Please log in via the Dashboard.")
    else:
        print("  - Cached token found. Exchanging for data...")
        om = OptionsManager(stocko_auth=auth)
        res = om.fetch_from_stocko()
        if res:
            df, spot, expiry = res
            print(f"  - SUCCESS: Stocko returned {len(df)} rows. Spot: {spot}, Expiry: {expiry}")
        else:
            print("  - FAILED: Stocko API call failed. Check logs above for specific errors.")

    # 2. Test Local DB
    print("\n[2/3] Testing Local Database snapshots...")
    om = OptionsManager()
    res = om.fetch_from_db()
    if res:
        df, spot, expiry = res
        from datetime import datetime
        # We assume the first row has the timestamp in the manager
        print(f"  - SUCCESS: DB contains snapshot with spot {spot}.")
    else:
        print("  - FAILED: No valid snapshots found in 'option_chain_snapshots' table.")

    # 3. Test NSE Scraper
    print("\n[3/3] Testing NSE Scraper...")
    om = OptionsManager()
    data = om.fetch_data()
    if data:
        df, spot, expiry = om.process_chain(data)
        print(f"  - SUCCESS: NSE Scraper returned {len(df)} rows. Spot: {spot}")
    else:
        print("  - FAILED: NSE Scraper failed. Most likely a 403 Forbidden or Timeout.")

    print("\nDiagnostics Complete.")

if __name__ == "__main__":
    run_diagnostics()
