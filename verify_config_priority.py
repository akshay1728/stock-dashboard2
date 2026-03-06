import sqlite3
import os
from config import Config

def test():
    # 1. Setup a dummy DB with specific values
    DB_PATH = "breadth_data.db"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS api_config (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT OR REPLACE INTO api_config (key, value) VALUES ('API_KEY', 'db_api_key')")
    c.execute("INSERT OR REPLACE INTO api_config (key, value) VALUES ('API_SECRET', 'db_api_secret')")
    conn.commit()
    conn.close()

    # 2. Reset Config (it might have loaded .env already)
    Config.API_KEY = "env_api_key"
    Config.API_SECRET = "env_api_secret"

    # 3. Load from DB
    Config.load_from_db()

    # 4. Assert
    print(f"Config.API_KEY: {Config.API_KEY}")
    print(f"Config.API_SECRET: {Config.API_SECRET}")

    if Config.API_KEY == 'db_api_key' and Config.API_SECRET == 'db_api_secret':
        print("SUCCESS: Database values override environment variables.")
    else:
        print("FAILURE: Database values did NOT override environment variables.")

if __name__ == "__main__":
    test()
