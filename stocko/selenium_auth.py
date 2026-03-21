from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from threading import Thread
import time
import logging
import pyotp
from urllib.parse import urlparse

# Set up logging
logger = logging.getLogger("stocko.selenium_auth")

def selenium_login(username, password, totp_secret, redirect_url='http://127.0.0.1:65015/'):
    """Function to perform automated OAuth2 login using Selenium"""
    driver = None
    try:
        logger.info("Starting automated login via Selenium")

        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        # Add some common options to avoid detection/issues
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        driver = webdriver.Chrome(options=chrome_options)
        logger.info("Browser initialized")

        # Determine the local initiation URL
        parsed_url = urlparse(redirect_url)
        base_redirect = f"{parsed_url.scheme}://{parsed_url.netloc}"
        init_url = f"{base_redirect}/getcode"

        driver.get(init_url)
        logger.info(f"Navigated to initiation URL: {init_url}")

        # 1. Login Form
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "login_form")))
            logger.info("Login form detected")
        except TimeoutException:
            logger.error(f"Login form not found. Current URL: {driver.current_url}")
            if "invalid_client" in driver.current_url:
                logger.error("OAuth Client ID (API Key) is invalid. Check settings.")
            raise Exception("Login form timeout")

        driver.find_element(By.NAME, "login_id").send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        logger.info("Credentials submitted")

        # 2. TOTP Verification
        try:
            # Wait for TOTP field
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//input[@type='password']")))
            logger.info("TOTP field detected")

            totp = pyotp.TOTP(totp_secret)
            totp_code = totp.now()
            totp_field = driver.find_element(By.XPATH, "//input[@type='password']")
            totp_field.send_keys(totp_code)

            # Click submit (it's often the same button type or index)
            driver.find_element(By.XPATH, "//button[@type='submit']").click()
            logger.info("TOTP submitted")
        except TimeoutException:
            logger.warning("TOTP field not found, login might have failed or skipped 2FA.")
        except Exception as e:
            logger.error(f"Error during TOTP stage: {e}")

        # Check for error message
        time.sleep(2)
        if "Invalid TOTP" in driver.page_source:
            logger.error("Automatic TOTP failed: Invalid TOTP")
            raise Exception("Invalid TOTP")
        else:
            logger.info("TOTP accepted")

        # 3. Consent/Authorize Page (if it appears)
        try:
            logger.info("Checking for consent/authorize button...")
            consent_buttons = ["Authorize", "Approve", "Allow", "Confirm", "Login", "Accept", "Proceed"]
            button_xpath = " | ".join([f"//button[contains(text(), '{txt}')]" for txt in consent_buttons])
            button_xpath += " | " + " | ".join([f"//input[@type='submit' and contains(@value, '{txt}')]" for txt in consent_buttons])

            auth_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, button_xpath)))
            button_text = auth_button.text or auth_button.get_attribute('value')
            auth_button.click()
            logger.info(f"Consent button clicked: {button_text}")
        except TimeoutException:
            logger.debug("No consent button found (might have auto-redirected)")

        # 4. Wait for Redirect Completion
        logger.info("Waiting for redirect back to local server (60s timeout)...")
        try:
            # Look for indicators of success on localhost or final destination
            WebDriverWait(driver, 60).until(
                lambda d: "see terminal for logs" in d.page_source.lower() or
                         "127.0.0.1" in d.current_url or
                         "localhost" in d.current_url or
                         "success" in d.current_url.lower()
            )
            logger.info(f"Redirect completed successfully. Final URL: {driver.current_url}")
            # Ensure enough time for Flask to process the token if it's the final landing
            time.sleep(2)
        except TimeoutException:
            logger.error(f"Timeout waiting for redirect. Current URL: {driver.current_url}")
            logger.debug(f"Page content snippet: {driver.page_source[:500]}")
            raise Exception("Redirect timeout")

    except Exception as e:
        logger.error(f"Selenium automation failed: {str(e)}")
        raise
    finally:
        if driver:
            driver.quit()
            logger.info("Browser closed")

def start_selenium_thread(username, password, totp_secret, redirect_url='http://127.0.0.1:65015/'):
    """Function to start selenium automation in a separate thread"""
    selenium_thread = Thread(target=selenium_login, args=(username, password, totp_secret, redirect_url))
    selenium_thread.daemon = True
    selenium_thread.start()
    return selenium_thread
