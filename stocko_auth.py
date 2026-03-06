import os
import time
import logging
import json
import threading
import webbrowser
import secrets
import string
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from pyoauthbridge import Connect
from config import Config

logger = logging.getLogger(__name__)

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Local server handler to capture the OAuth code from the redirect."""
    def log_message(self, format, *args):
        pass # Suppress HTTP logs in the console

    def do_GET(self):
        parsed_path = urlparse(self.path)

        # 1. Handle Initiation Route (e.g., /getcode as requested by the user)
        if parsed_path.path == '/getcode':
            self.send_response(302)
            auth_url = self.server.auth_instance._build_auth_url()
            self.send_header('Location', auth_url)
            self.end_headers()
            return

        # 2. Handle Redirect Callback Route (/)
        query = parse_qs(parsed_path.query)
        code = query.get('code', [None])[0]
        state = query.get('state', [None])[0]

        if code:
            logger.info("Local Server: Received authorization code from redirect.")
            # Check state if we have it to prevent CSRF
            if self.server.expected_state and state != self.server.expected_state:
                logger.error(f"Local Server: CSRF detected! Expected state {self.server.expected_state}, got {state}")
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Error: Invalid state parameter. CSRF detected.")
                return

            self.server.captured_code = code
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><body style='font-family: sans-serif; text-align: center; padding: 50px;'>")
            self.wfile.write(b"<h1>Success!</h1><p>Authentication code captured successfully. You can close this window and return to the dashboard.</p>")
            self.wfile.write(b"</body></html>")

            # Use a short timer to shut down the server after responding
            def shutdown():
                logger.info("Local Server: Shutting down.")
                self.server.shutdown()
            threading.Timer(1, shutdown).start()
        else:
            logger.debug("Local Server: Received non-callback GET request.")
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Ready to capture OAuth code...")

class StockoAuth:
    TOKEN_CACHE = "stocko_token.json"

    def __init__(self):
        self.client = None
        self.access_token = None
        self._refresh_config()

    def _refresh_config(self):
        """Ensures we have the absolute latest credentials from the database."""
        Config.load_from_db()
        self.client_id = Config.API_KEY
        self.client_secret = Config.API_SECRET
        # Standardize on port 65015 as per user's preference
        self.redirect_url = (Config.REDIRECT_URL or "http://127.0.0.1:65015/").strip()
        self.base_url = (Config.BASE_URL or "https://primusapi.tradelab.in").strip().rstrip('/')
        self.client_code = Config.CLIENT_CODE
        self.password = Config.PASSWORD

    def login(self, allow_browser=True):
        """
        Main entry point for authentication.
        allow_browser: If True, will initiate browser flow if needed.
                      Set to False for background services.
        """
        logger.info("Auth: Initiating login sequence...")
        self._refresh_config() # Refresh before every login attempt

        if self._load_cached_token():
            logger.info("Auth: Found cached access token. Validating...")
            self._init_client()
            if self._validate_token():
                logger.info("Auth: Cached token is valid. Login successful.")
                return True
            else:
                logger.warning("Auth: Cached token invalid or expired.")

        if not allow_browser:
            logger.warning("Auth: Manual authentication required, but browser initiation is disabled for this context.")
            return False

        logger.info("Auth: No valid token. Triggering browser-based OAuth flow...")
        if self.login_via_browser():
            self._save_token()
            self._init_client()
            logger.info("Auth: Browser login sequence complete.")
            return True

        logger.error("Auth: Browser login sequence failed.")
        return False

    def _build_auth_url(self, state=None):
        """Helper to construct the authorization URL."""
        if not state:
            state = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
        return f"{self.base_url}/oauth2/auth?client_id={quote(str(self.client_id))}&redirect_uri={quote(str(self.redirect_url))}&response_type=code&scope=orders%20holdings&state={state}"

    def login_via_browser(self):
        """
        Starts a local callback server, opens the browser to the OAuth URL,
        and waits for the authorization code.
        """
        logger.info("Browser Auth: Refreshing configuration...")
        self._refresh_config()
        if not all([self.client_id, self.client_secret]):
            logger.error("Browser Auth: CRITICAL - Missing API Key or Secret. Configuration incomplete.")
            return False

        # 1. Start local callback server
        # Parse port from redirect_url
        try:
            port = int(urlparse(self.redirect_url).port or 65015)
        except:
            port = 65015

        server = HTTPServer(('127.0.0.1', port), OAuthCallbackHandler)
        server.auth_instance = self
        server.captured_code = None
        # Use a fixed state for easier manual testing or allow any state if not provided
        server.expected_state = None

        # Start server in a thread so we can use serve_forever and shut it down cleanly
        threading.Thread(target=server.serve_forever, daemon=True).start()

        # 2. Open browser to the local initiation route
        # This will redirect to Stocko website
        init_url = f"http://127.0.0.1:{port}/getcode"
        logger.info(f"Opening browser to initiation URL: {init_url}")

        # Attempt to use the default system browser
        # On many systems, Chrome is the default. webbrowser.open usually respects system defaults.
        try:
            # try to use chrome explicitly if possible, else fallback
            try:
                chrome = webbrowser.get('google-chrome')
                chrome.open(init_url, new=2)
            except:
                try:
                    chrome = webbrowser.get('chrome')
                    chrome.open(init_url, new=2)
                except:
                    webbrowser.open(init_url, new=2)
        except Exception as e:
            logger.warning(f"Could not open browser automatically: {e}")
            print(f"\nPLEASE OPEN THIS URL MANUALLY IN CHROME:\n{init_url}\n")

        # 3. Wait for code with a timeout
        logger.info(f"Listening for OAuth callback on port {port} (Timeout: 120s)...")
        start_wait = time.time()
        while server.captured_code is None and (time.time() - start_wait) < 120:
            time.sleep(1)

        server.shutdown()
        server.server_close()

        if server.captured_code:
            code = server.captured_code
            logger.info("Captured authorization code. Exchanging for access token...")

            # Step 4: Exchange code for token
            import requests
            from requests.auth import HTTPBasicAuth
            token_url = f"{self.base_url}/oauth2/token"

            # The API requires 'client_secret_basic' auth method
            auth = HTTPBasicAuth(self.client_id, self.client_secret)

            token_payload = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': self.redirect_url
            }

            logger.info(f"Exchanging code for token at {token_url} using HTTP Basic Auth")
            res = requests.post(token_url, data=token_payload, auth=auth)

            if res.status_code == 200:
                token_data = res.json()
                self.access_token = token_data.get('access_token')
                logger.info("Access token acquired successfully.")
                return self.access_token is not None
            else:
                logger.error(f"Token exchange failed: {res.status_code} - {res.text}")
                return False
        else:
            logger.error("Failed to capture authorization code from browser flow.")
            return False

    def _init_client(self):
        self._refresh_config()
        self.client = Connect(self.client_id, self.client_secret, self.redirect_url, self.base_url)
        self.client.set_access_token(self.access_token)

    def _load_cached_token(self):
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
        try:
            res = self.client.fetch_profile({'client_id': self.client_code})
            return res.get("status") == "success"
        except:
            return False
