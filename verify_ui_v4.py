from playwright.sync_api import sync_playwright

def verify():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto('http://localhost:8501')
        page.wait_for_timeout(10000)

        # Take screenshot of home - should NOT have popup
        page.screenshot(path='verify_home_no_popup.png')

        # Go to settings
        page.get_by_text('⚙️ Settings').click()
        page.wait_for_timeout(3000)

        # Screenshot of settings with API config
        page.screenshot(path='verify_settings_api.png')

        browser.close()

if __name__ == "__main__":
    verify()
