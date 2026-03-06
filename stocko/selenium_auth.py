from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from threading import Thread
import time
import logging
import pyotp

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def selenium_login(username, password, totp_secret, redirect_url='http://127.0.0.1:65015/'):
    """Function to perform automated OAuth2 login using Selenium"""
    driver = None
    try:
        logger.info("Starting selenium automation")

        # Set up Chrome options
        chrome_options = Options()
        chrome_options.add_argument('--start-maximized')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--headless')

        # Initialize the Chrome WebDriver
        driver = webdriver.Chrome(options=chrome_options)
        logger.info("Chrome WebDriver initialized")

        # Navigate to getcode endpoint which redirects to OAuth2 authorization
        # Ensure redirect_url is used to reach the local server's getcode route
        from urllib.parse import urlparse
        parsed_url = urlparse(redirect_url)
        # We assume the Flask server is running on the same host/port as redirect_url
        # but the route is always /getcode
        base_redirect = f"{parsed_url.scheme}://{parsed_url.netloc}"
        driver.get(f'{base_redirect}/getcode')
        logger.info(f"Navigated to {base_redirect}/getcode endpoint")

        # Wait for login form
        try:
            form = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "login_form"))
            )
        except TimeoutException:
            logger.error(f"Login form not found. Current URL: {driver.current_url}")
            logger.debug(f"Page Source: {driver.page_source[:1000]}...")
            raise
        logger.info("Login form found")

        # Find and fill username field
        username_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "login_id"))
        )
        username_field.clear()
        username_field.send_keys(username)
        logger.info("Username entered")

        # Find and fill password field
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "password"))
        )
        password_field.clear()
        password_field.send_keys(password)
        logger.info("Password entered")

        # Find and click submit button
        submit_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//button[@type='submit']"))
        )
        submit_button.click()
        logger.info("Submit button clicked")

        # Try automatic TOTP first
        logger.info("Attempting automatic TOTP")
        totp = pyotp.TOTP(totp_secret)
        totp_code = totp.now()

        # Find and fill TOTP field
        totp_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='password']"))
        )
        totp_field.clear()
        totp_field.send_keys(totp_code)
        logger.info("Automatic TOTP code entered")

        # Find and click TOTP submit button
        totp_submit = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//button[@type='submit']"))
        )
        totp_submit.click()
        logger.info("TOTP submitted")

        # Check for error message
        try:
            error_message = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Invalid TOTP')]"))
            )
            logger.warning("Automatic TOTP failed. Waiting for manual TOTP entry.")

            # Re-find the TOTP field for manual entry
            logger.info("Re-locating TOTP field for manual entry")
            totp_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='password']"))
            )
            totp_field.clear()

            # Wait for manual entry and submission
            logger.info("Please enter TOTP code manually")
            WebDriverWait(driver, 120).until_not(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Invalid TOTP')]"))
            )
            logger.info("Manual TOTP entry completed")
        except TimeoutException:
            # No error message found, assume TOTP was accepted
            logger.info("TOTP accepted")

        # Some systems require clicking an "Authorize" button
        try:
            auth_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Authorize')]"))
            )
            auth_button.click()
            logger.info("Authorize button clicked")
        except:
            pass

        # Wait for OAuth2 authorization to complete and redirect
        try:
            WebDriverWait(driver, 60).until(
                lambda driver: "see terminal for logs" in driver.page_source.lower()
            )
            logger.info("OAuth2 authorization completed successfully")
        except TimeoutException:
            logger.error(f"Timeout waiting for OAuth2 authorization to complete. Current URL: {driver.current_url}")
            # Log a snippet of the page source for debugging
            logger.debug(f"Page Source: {driver.page_source[:500]}...")
            raise

    except Exception as e:
        logger.error(f"Error during selenium automation: {str(e)}")
        raise
    finally:
        if driver:
            driver.close()
            driver.quit()
            logger.info("Chrome WebDriver closed")

def start_selenium_thread(username, password, totp_secret, redirect_url='http://127.0.0.1:65015/'):
    """Function to start selenium automation in a separate thread"""
    selenium_thread = Thread(target=selenium_login, args=(username, password, totp_secret, redirect_url))
    selenium_thread.daemon = True  # Thread will be terminated when main thread exits
    selenium_thread.start()
    return selenium_thread
