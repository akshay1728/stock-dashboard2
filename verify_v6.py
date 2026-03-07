from playwright.sync_api import sync_playwright, expect
import time

def verify_ui():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            print("Navigating to app...")
            page.goto("http://localhost:8501", timeout=30000)
            time.sleep(15)

            # Click by text
            print("Clicking Strategy Builder...")
            page.get_by_text("Strategy Builder").first.click()
            time.sleep(10)
            page.screenshot(path="verify_strategy_builder_v6.png")
            print("Strategy Builder screenshot saved")

            browser.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify_ui()
