import sqlite3
import logging
from config import Config

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or Config.DATABASE_URL.replace("sqlite:///", "")
        self.init_db()

    def init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            c.execute('''CREATE TABLE IF NOT EXISTS option_chain_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                symbol TEXT,
                expiry_date TEXT,
                strike REAL,
                option_type TEXT,
                ltp REAL,
                bid REAL,
                ask REAL,
                volume INTEGER,
                open_interest INTEGER,
                oi_change INTEGER,
                implied_volatility REAL,
                underlying_price REAL
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS index_prices (
                timestamp DATETIME,
                symbol TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                last_price REAL,
                PRIMARY KEY (timestamp, symbol)
            )''')

            # 1m History tables for simulator
            c.execute('''CREATE TABLE IF NOT EXISTS index_1m_history (
                timestamp DATETIME,
                symbol TEXT,
                open REAL, high REAL, low REAL, close REAL, volume INTEGER,
                PRIMARY KEY (timestamp, symbol)
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS option_1m_history (
                timestamp DATETIME,
                symbol TEXT,
                expiry_date TEXT,
                strike REAL,
                option_type TEXT,
                ltp REAL,
                open_interest INTEGER,
                implied_volatility REAL,
                PRIMARY KEY (timestamp, symbol, expiry_date, strike, option_type)
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS api_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )''')

            conn.commit()
            conn.close()
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")

    def save_index_data(self, data):
        if not data: return
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            ts = data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            c.execute('''INSERT OR REPLACE INTO index_prices VALUES (?,?,?,?,?,?,?)''',
                      (ts, data['symbol'], data['open'], data['high'], data['low'], data['close'], data['last_price']))

            # Archive to 1m history
            c.execute('''INSERT OR REPLACE INTO index_1m_history VALUES (?,?,?,?,?,?,?)''',
                      (ts, data['symbol'], data['open'], data['high'], data['low'], data['last_price'], 0))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving index data: {e}")

    def save_option_chain(self, chain_data):
        if not chain_data: return
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            for row in chain_data:
                ts = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                c.execute('''INSERT INTO option_chain_snapshots (
                    timestamp, symbol, expiry_date, strike, option_type,
                    ltp, bid, ask, volume, open_interest, oi_change,
                    implied_volatility, underlying_price
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (ts, row['symbol'], row['expiry_date'],
                 row['strike'], row['option_type'], row['ltp'], row['bid'], row['ask'],
                 row['volume'], row['open_interest'], row['oi_change'], row['implied_volatility'],
                 row['underlying_price']))

                # Archive to 1m history
                c.execute('''INSERT OR REPLACE INTO option_1m_history (
                    timestamp, symbol, expiry_date, strike, option_type,
                    ltp, open_interest, implied_volatility
                ) VALUES (?,?,?,?,?,?,?,?)''',
                (ts, row['symbol'], row['expiry_date'], row['strike'], row['option_type'],
                 row['ltp'], row['open_interest'], row['implied_volatility']))

            conn.commit()
            conn.close()
            logger.info(f"Saved {len(chain_data)} option chain records.")
        except Exception as e:
            logger.error(f"Error saving option chain: {e}")

    def import_csv(self, file_path, table_name):
        """Imports a CSV into the specified historical table."""
        import pandas as pd
        try:
            df = pd.read_csv(file_path)
            # Ensure timestamp is in correct format
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')

            conn = sqlite3.connect(self.db_path)
            df.to_sql(table_name, conn, if_exists='append', index=False)
            conn.close()
            return True, f"Imported {len(df)} records into {table_name}."
        except Exception as e:
            logger.error(f"Error importing CSV: {e}")
            return False, str(e)

    def get_history_stats(self):
        """Returns statistics of the historical tables."""
        stats = {}
        try:
            conn = sqlite3.connect(self.db_path)
            for table in ['index_1m_history', 'option_1m_history']:
                res = conn.execute(f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table}").fetchone()
                stats[table] = {
                    'count': res[0],
                    'start': res[1],
                    'end': res[2]
                }
            conn.close()
        except Exception as e:
            logger.error(f"Error getting history stats: {e}")
        return stats

    def save_option_chain_no_archive(self, chain_data):
        if not chain_data: return
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            for row in chain_data:
                c.execute('''INSERT INTO option_chain_snapshots (
                    timestamp, symbol, expiry_date, strike, option_type,
                    ltp, bid, ask, volume, open_interest, oi_change,
                    implied_volatility, underlying_price
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'), row['symbol'], row['expiry_date'],
                 row['strike'], row['option_type'], row['ltp'], row['bid'], row['ask'],
                 row['volume'], row['open_interest'], row['oi_change'], row['implied_volatility'],
                 row['underlying_price']))
            conn.commit()
            conn.close()
            logger.info(f"Saved {len(chain_data)} option chain records.")
        except Exception as e:
            logger.error(f"Error saving option chain: {e}")
