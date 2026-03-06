import logging
import sys
from stocko_auth import StockoAuth
from config import Config

logging.basicConfig(level=logging.INFO)

def test():
    # Set dummy configs if none exist
    if not Config.API_KEY:
        Config.save_to_db({
            "API_KEY": "dummy_key",
            "API_SECRET": "dummy_secret",
            "CLIENT_CODE": "dummy_client",
            "PASSWORD": "dummy_password",
            "TOTP_SECRET": "ABCDEF1234567890"
        })

    auth = StockoAuth()
    print("Attempting login...")
    success = auth.login()
    print(f"Login success: {success}")

if __name__ == "__main__":
    test()
