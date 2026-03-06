import logging
import sys
import os
from stocko_auth import StockoAuth
from config import Config

logging.basicConfig(level=logging.INFO)

def test():
    # Set dummy configs if none exist
    # Using a valid base32 dummy secret for pyotp
    Config.save_to_db({
        "API_KEY": "dummy_key",
        "API_SECRET": "dummy_secret",
        "CLIENT_CODE": "dummy_client",
        "PASSWORD": "dummy_password",
        "TOTP_SECRET": "JBSWY3DPEHPK3PXP"
    })

    auth = StockoAuth()
    print("Attempting login...")
    # This will still fail actual login because credentials are dummy,
    # but we want to see it get past the TOTP generation and reach the login form submission.
    success = auth.login()
    print(f"Login success: {success}")

if __name__ == "__main__":
    test()
