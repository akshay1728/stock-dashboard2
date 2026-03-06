import threading
import time
import requests
from stocko_auth import StockoAuth
from config import Config

def simulate_browser_callback(port, code):
    time.sleep(2) # Wait for server to start
    url = f"http://127.0.0.1:{port}/?code={code}&state=MOCK_STATE"
    print(f"Simulating browser callback to {url}")
    try:
        res = requests.get(url)
        print(f"Callback response: {res.status_code}")
    except Exception as e:
        print(f"Callback failed: {e}")

def test_browser_flow():
    # Setup dummy config
    Config.save_to_db({
        "API_KEY": "dummy_key",
        "API_SECRET": "dummy_secret",
        "REDIRECT_URL": "http://127.0.0.1:65015/"
    })

    auth = StockoAuth()

    # We need to mock _build_auth_url and the token exchange since we don't have a real API
    # But we can at least test the server starting and capturing the code.

    # To test the capture, we start the login in a thread
    # and hit it with a mock request

    def run_login():
        # This will block until handle_request is done
        auth.login_via_browser()

    t = threading.Thread(target=run_login)
    t.start()

    # Wait a bit then send the mock callback
    simulate_browser_callback(65015, "TEST_AUTH_CODE")

    t.join(timeout=10)
    print("Test complete.")

if __name__ == "__main__":
    test_browser_flow()
