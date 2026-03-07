import os
import time
import logging
import json
from datetime import datetime
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
        self._load_cached_token()

    def _refresh_config(self):
        """Ensures we have the absolute latest credentials from the database."""
        Config.load_from_db()
        self.client_id = Config.API_KEY
        self.client_secret = Config.API_SECRET
        self.redirect_url = (Config.REDIRECT_URL or "http://127.0.0.1:65015/").strip()
        self.base_url = (Config.BASE_URL or "https://api.stocko.in").strip().rstrip('/')
        self.client_code = Config.CLIENT_CODE
        self.password = Config.PASSWORD
        self.totp_secret = Config.TOTP_SECRET

    def login(self):
        """
        Main entry point for authentication using automated login.
        """
        logger.info("Auth: Initiating login sequence...")
        self._refresh_config()

        # 1. Check if existing token is valid
        if self._load_cached_token():
            logger.info("Auth: Found cached token, validating...")
            if self._init_client(use_cached=True):
                if self._validate_token():
                    logger.info("Auth: Cached token is valid. Login successful.")
                    return True
                else:
                    logger.warning("Auth: Cached token invalid or expired. Re-authenticating...")
            else:
                logger.warning("Auth: Failed to initialize client with cached token.")

        # 2. Perform automated login via Selenium
        logger.info("Auth: Triggering automated Selenium login...")
        try:
            # We initialize AlphaTrade without access_token to force automated login
            self.client = AlphaTrade(
                login_id=self.client_code,
                password=self.password,
                totp=self.totp_secret,
                client_secret=self.client_secret,
                client_id=self.client_id,
                redirect_url=self.redirect_url,
                master_contracts_to_download=['NSE', 'NFO']
            )

            # Check for token in client instance
            token = getattr(self.client, 'access_token', None) or \
                    getattr(self.client, '_AlphaTrade__access_token', None)

            if token:
                self.access_token = token
                self._save_token()
                logger.info("Auth: Automated login successful. Token acquired.")
                return True

            # Re-check file cache
            if self._load_cached_token():
                logger.info("Auth: Token found in cache after automated login.")
                return True

            logger.error("Auth: Automated login process completed but no access token was found.")
            return False
        except Exception as e:
            logger.error(f"Auth: Automated login failed: {e}")
            return False

    def _init_client(self, use_cached=False):
        try:
            token_to_use = self.access_token if use_cached else None
            self.client = AlphaTrade(
                login_id=self.client_code,
                password=self.password,
                totp=self.totp_secret,
                client_secret=self.client_secret,
                client_id=self.client_id,
                redirect_url=self.redirect_url,
                access_token=token_to_use,
                master_contracts_to_download=['NSE', 'NFO']
            )

            # Explicitly set access token in client if we passed one
            if use_cached and self.access_token:
                self.client.set_access_token(self.access_token)

            return True
        except Exception as e:
            logger.debug(f"Auth: Client initialization failed: {e}")
            return False

    def _load_cached_token(self):
        # 1. Try dashboard cache
        if os.path.exists(self.TOKEN_CACHE):
            try:
                with open(self.TOKEN_CACHE, 'r') as f:
                    data = json.load(f)

                # New Day Check: Clear if from previous day
                ts = data.get("timestamp")
                if ts:
                    cached_date = datetime.fromtimestamp(ts).date()
                    if cached_date < datetime.now().date():
                        logger.info("Auth: Cached token is from a previous day. Clearing...")
                        os.remove(self.TOKEN_CACHE)
                        if os.path.exists(self.LIB_TOKEN_CACHE): os.remove(self.LIB_TOKEN_CACHE)
                        return False

                self.access_token = data.get("access_token")
                if self.access_token: return True
            except: pass

        # 2. Try library cache
        if os.path.exists(self.LIB_TOKEN_CACHE):
            try:
                with open(self.LIB_TOKEN_CACHE, 'r') as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    if self.access_token:
                        self._save_token() # Sync to dashboard cache
                        return True
            except: pass

        return False

    def _save_token(self):
        if not self.access_token: return
        try:
            # Save to dashboard cache
            with open(self.TOKEN_CACHE, 'w') as f:
                json.dump({"access_token": self.access_token, "timestamp": time.time()}, f)
            # Ensure library cache is also in sync
            with open(self.LIB_TOKEN_CACHE, 'w') as f:
                json.dump({"access_token": self.access_token, "date_created": time.strftime("%d-%m-%YT%H:%M:%S")}, f)
        except Exception as e:
            logger.error(f"Error saving token to cache: {e}")

    def _validate_token(self):
        if not self.access_token or not self.client:
            logger.debug(f"Validation failed: access_token present={bool(self.access_token)}, client present={bool(self.client)}")
            return False
        try:
            res = self.client.get_profile()
            logger.info(f"Token validation response: {res}")
            if isinstance(res, dict):
                # Stocko API success indicators
                if res.get("status") == "success": return True
                if res.get("error_code") == 0: return True
                # SAS/Stocko API weirdness: sometimes errors are "safe to proceed"
                if "AccountInfoService" in str(res.get("message", "")):
                    return True
                if res.get("data") and isinstance(res.get("data"), dict) and "client_id" in res["data"]:
                    return True
            return False
        except Exception as e:
            logger.error(f"Token validation exception: {e}")
            return False
