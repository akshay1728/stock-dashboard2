import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from options_strategy import OptionsStrategy

class SimulatorManager:
    def __init__(self, symbol="^NSEI"):
        self.symbol = symbol
        self.data = pd.DataFrame()

    def fetch_historical_intraday(self, days=5, interval="5m", use_local=True):
        """Fetches historical intraday data for replay."""
        if use_local:
            import sqlite3
            from config import Config
            db_path = Config.DATABASE_URL.replace("sqlite:///", "")
            conn = sqlite3.connect(db_path)
            # Try to get data from local 1m history
            query = "SELECT * FROM index_1m_history ORDER BY timestamp ASC"
            df = pd.read_sql_query(query, conn)
            conn.close()
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                # Map columns to yfinance format
                df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
                self.data = df
                return True

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        df = yf.download(self.symbol, start=start_date, end=end_date, interval=interval)
        if not df.empty:
            # Flatten columns if multi-index
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            self.data = df
            return True
        return False

    def get_price_at(self, timestamp):
        """Returns the OHLV at a specific timestamp."""
        if self.data.empty: return None
        try:
            # Find the closest timestamp before or at the requested time
            idx = self.data.index.get_indexer([timestamp], method='pad')[0]
            if idx == -1: return None
            return self.data.iloc[idx]
        except:
            return None

    def get_option_price(self, spot, strike, dte_days, option_type, iv, r=0.07, timestamp=None):
        """Returns actual historical price if available, else synthetic."""
        if timestamp:
            import sqlite3
            from config import Config
            db_path = Config.DATABASE_URL.replace("sqlite:///", "")
            conn = sqlite3.connect(db_path)
            ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            # Look for exact or closest prior tick within 1 minute
            query = "SELECT ltp FROM option_1m_history WHERE timestamp <= ? AND strike = ? AND option_type = ? ORDER BY timestamp DESC LIMIT 1"
            res = conn.execute(query, (ts_str, strike, option_type)).fetchone()
            conn.close()
            if res: return res[0]

        # Use synthetic only if real data is missing and it's a "backfill" mode
        # For professional simulator, we prefer strict real data
        T = dte_days / 365.0
        price = OptionsStrategy.black_scholes(S=spot, K=strike, T=T, r=r, sigma=iv, option_type=option_type.lower())
        return price

    def get_available_strikes(self, spot, step=50, count=10):
        """Generates a list of strikes around the spot."""
        atm = round(spot / step) * step
        strikes = [atm + i * step for i in range(-count, count + 1)]
        return strikes
