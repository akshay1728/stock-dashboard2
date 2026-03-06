import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_PATH = os.getenv("DATABASE_URL", "sqlite:///breadth_data.db").replace("sqlite:///", "")

    # Defaults from .env
    API_KEY = os.getenv("STOCKO_API_KEY")
    API_SECRET = os.getenv("STOCKO_API_SECRET")
    REDIRECT_URL = os.getenv("STOCKO_REDIRECT_URL", "http://127.0.0.1/")
    BASE_URL = os.getenv("STOCKO_BASE_URL", "https://api.stocko.in")
    CLIENT_CODE = os.getenv("STOCKO_CLIENT_CODE")
    PASSWORD = os.getenv("STOCKO_PASSWORD")
    TOTP_SECRET = os.getenv("STOCKO_TOTP_SECRET")

    SYMBOL = os.getenv("COLLECTION_SYMBOL", "NIFTY")
    FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL_SECONDS", 60))
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///breadth_data.db")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    DRY_RUN = os.getenv("DRY_RUN", "False").lower() == "true"

    @classmethod
    def load_from_db(cls):
        """Loads API configuration from SQLite database, overriding .env."""
        try:
            if not os.path.exists(cls.DB_PATH):
                return
            conn = sqlite3.connect(cls.DB_PATH)
            c = conn.cursor()
            # Check if table exists
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='api_config'")
            if not c.fetchone():
                conn.close()
                return

            c.execute("SELECT key, value FROM api_config")
            rows = c.fetchall()
            for key, value in rows:
                if hasattr(cls, key) and value:
                    if isinstance(value, str):
                        value = value.strip()
                    setattr(cls, key, value)
            conn.close()
        except Exception as e:
            print(f"Error loading config from DB: {e}")

    @classmethod
    def save_to_db(cls, config_dict):
        """Saves configuration to database."""
        try:
            conn = sqlite3.connect(cls.DB_PATH)
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS api_config (key TEXT PRIMARY KEY, value TEXT)")
            for key, value in config_dict.items():
                if isinstance(value, str):
                    value = value.strip()
                c.execute("INSERT OR REPLACE INTO api_config (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            conn.close()
            # Refresh current class attributes
            cls.load_from_db()
        except Exception as e:
            print(f"Error saving config to DB: {e}")

    @classmethod
    def validate(cls):
        missing = []
        for attr in ["API_KEY", "API_SECRET", "CLIENT_CODE", "PASSWORD", "TOTP_SECRET"]:
            if not getattr(cls, attr):
                missing.append(attr)
        return missing

# Initial load
Config.load_from_db()
