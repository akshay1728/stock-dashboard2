import os
import time
import logging
import json
from stocko import AlphaTrade
from config import Config

logger = logging.getLogger(__name__)

class StockoAuth:
    TOKEN_CACHE = "stocko_token.json"
    LIB_TOKEN_CACHE = "stocko/token.json"

    def __init__(self):
        self.client = None
        self.access_token = None
        self._refresh_config()

    def _refresh_config(self):
        """Ensures we have the absolute latest credentials from the database."""
        Config.load_from_db()
        self.client_id = Config.API_KEY
        self.client_secret = Config.API_SECRET
        self.redirect_url = (Config.REDIRECT_URL or "http://127.0.0.1/").strip()
        self.base_url = (Config.BASE_URL or "https://api.stocko.in").strip().rstrip('/')
        self.client_code = Config.CLIENT_CODE
        self.password = Config.PASSWORD
        self.totp_secret = Config.TOTP_SECRET

    def login(self, allow_browser=True):
        """
        Main entry point for authentication using automated login.
        """
        logger.info("Auth: Initiating automated login sequence...")
        self._refresh_config()

        try:
            # Check for existing valid token
            if self._load_cached_token():
                logger.info("Auth: Found cached access token. Initializing client...")
                try:
                    self.client = AlphaTrade(
                        login_id=self.client_code,
                        password=self.password,
                        totp=self.totp_secret,
                        client_secret=self.client_secret,
                        access_token=self.access_token,
                        master_contracts_to_download=['NSE', 'NFO']
                    )
                    if self._validate_token():
                        logger.info("Auth: Cached token is valid. Login successful.")
                        return True
                    else:
                        logger.warning("Auth: Cached token is invalid. Re-authenticating...")
                except Exception as e:
                    logger.warning(f"Auth: Failed to init with cached token: {e}. Re-authenticating...")

            # Perform automated login via Selenium (handled by AlphaTrade internally)
            self.client = AlphaTrade(
                login_id=self.client_code,
                password=self.password,
                totp=self.totp_secret,
                client_secret=self.client_secret,
                master_contracts_to_download=['NSE', 'NFO']
            )

            # Extract access token from the library's internal cache
            if os.path.exists(self.LIB_TOKEN_CACHE):
                with open(self.LIB_TOKEN_CACHE, 'r') as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self._save_token() # Sync with dashboard's cache

            logger.info("Auth: Automated login successful.")
            return True
        except Exception as e:
            logger.error(f"Auth: Automated login failed: {e}")
            return False

    def _load_cached_token(self):
        # First check dashboard's cache
        if os.path.exists(self.TOKEN_CACHE):
            try:
                with open(self.TOKEN_CACHE, 'r') as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    return self.access_token is not None
            except Exception as e:
                logger.error(f"Error loading cached token: {e}")
        return False

    def _save_token(self):
        try:
            with open(self.TOKEN_CACHE, 'w') as f:
                json.dump({"access_token": self.access_token, "timestamp": time.time()}, f)
        except Exception as e:
            logger.error(f"Error saving token to cache: {e}")

    def _validate_token(self):
        if not self.access_token:
            return False
        try:
            # Simple profile fetch to validate token
            res = self.client.get_profile()
            return res.get("status") == "success"
        except:
            return False
