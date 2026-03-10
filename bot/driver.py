import os
import shutil
from utils.logger import get_logger
from config.settings import IMPLICIT_WAIT, PAGE_LOAD_TIMEOUT, BROWSER_PROFILE

log = get_logger("Driver")

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


def _clean_cache():
    paths = [
        os.path.join(os.environ.get('APPDATA', ''), 'undetected_chromedriver'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'undetected_chromedriver'),
        os.path.join(os.environ.get('USERPROFILE', ''), '.wdm'),
    ]
    for p in paths:
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)
            log.info(f"Cleaned cache: {p}")


def create_driver() -> webdriver.Chrome:
    profile_dir = os.path.abspath(BROWSER_PROFILE)
    os.makedirs(profile_dir, exist_ok=True)

    options = Options()
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    log.info("Starting Chrome...")

    try:
        service = Service(ChromeDriverManager(driver_version="145.0.7632.160").install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        driver.implicitly_wait(IMPLICIT_WAIT)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        log.info("Chrome started successfully.")
        return driver
    except Exception as e:
        log.warning(f"Failed: {e} — cleaning cache and retrying...")
        _clean_cache()
        service = Service(ChromeDriverManager(driver_version="145.0.7632.160").install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.implicitly_wait(IMPLICIT_WAIT)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        log.info("Chrome started on retry.")
        return driver


def safe_quit(driver):
    try:
        if driver:
            driver.quit()
            log.info("Browser closed.")
    except Exception as e:
        log.debug(f"Driver quit error: {e}")