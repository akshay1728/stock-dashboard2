import pandas as pd
import yfinance as yf
import sqlite3
import logging
from datetime import datetime, timedelta
from config import Config
from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HistoricalBackfiller")

class HistoricalBackfiller:
    def __init__(self):
        self.db = Database()
        self.symbol = "^NSEI" # NIFTY 50

    def backfill_spot_data(self, years=1.5):
        """Fetches 1h data for the last 1.5 years and stores it."""
        logger.info(f"Backfilling Spot data for {years} years...")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(years * 365))

        # yfinance limits for 1h is 730 days
        df = yf.download(self.symbol, start=start_date, end=end_date, interval="1h")

        if df.empty:
            logger.error("Failed to fetch historical spot data.")
            return False

        # Flatten columns if multi-index
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        conn = sqlite3.connect(self.db.db_path)
        count = 0
        for ts, row in df.iterrows():
            ts_str = ts.strftime('%Y-%m-%d %H:%M:%S')
            try:
                conn.execute('''INSERT OR REPLACE INTO index_1m_history VALUES (?,?,?,?,?,?,?)''',
                            (ts_str, "NIFTY", row['Open'], row['High'], row['Low'], row['Close'], int(row['Volume'])))
                count += 1
            except Exception as e:
                logger.debug(f"Skip {ts_str}: {e}")

        conn.commit()
        conn.close()
        logger.info(f"Successfully backfilled {count} index records.")
        return True

    def get_recent_1m_data(self):
        """Fetch maximum possible 1m data (last 7 days)."""
        logger.info("Fetching recent 1m ticks (last 7 days)...")
        df = yf.download(self.symbol, period="7d", interval="1m")
        if df.empty: return

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        conn = sqlite3.connect(self.db.db_path)
        for ts, row in df.iterrows():
            ts_str = ts.strftime('%Y-%m-%d %H:%M:%S')
            conn.execute('''INSERT OR REPLACE INTO index_1m_history VALUES (?,?,?,?,?,?,?)''',
                        (ts_str, "NIFTY", row['Open'], row['High'], row['Low'], row['Close'], int(row['Volume'])))
        conn.commit()
        conn.close()
        logger.info("Recent 1m ticks archived.")

if __name__ == "__main__":
    backfiller = HistoricalBackfiller()
    backfiller.backfill_spot_data()
    backfiller.get_recent_1m_data()
