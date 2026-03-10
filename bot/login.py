# bot/login.py

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from utils.logger import get_logger
from config.settings import BASE_URL

log = get_logger("Login")

USERNAME_SELECTORS = [
    (By.XPATH, "//input[@formcontrolname='userid']"),
    (By.XPATH, "//input[@placeholder='User Name']"),
    (By.CSS_SELECTOR, "input[formcontrolname='userid']"),
    (By.ID, "userid"),
]
PASSWORD_SELECTORS = [
    (By.XPATH, "//input[@formcontrolname='password']"),
    (By.XPATH, "//input[@type='password']"),
    (By.CSS_SELECTOR, "input[formcontrolname='password']"),
]
CAPTCHA_IMG_SELECTORS = [
    (By.XPATH, "//app-captcha//img"),
    (By.XPATH, "//img[contains(@src,'captcha')]"),
    (By.CSS_SELECTOR, "app-captcha img"),
]
CAPTCHA_INPUT_SELECTORS = [
    (By.XPATH, "//input[@formcontrolname='captcha']"),
    (By.XPATH, "//input[@placeholder='Enter Captcha']"),
    (By.CSS_SELECTOR, "input[formcontrolname='captcha']"),
]
LOGIN_BTN_SELECTORS = [
    (By.XPATH, "//button[contains(text(),'SIGN IN')]"),
    (By.XPATH, "//button[contains(text(),'Login')]"),
    (By.XPATH, "//button[@type='submit']"),
]
LOGIN_LINK_SELECTORS = [
    (By.XPATH, "//a[contains(@class,'loginText')]"),
    (By.XPATH, "//span[contains(text(),'LOGIN')]"),
    (By.XPATH, "//a[contains(text(),'LOGIN')]"),
    (By.CSS_SELECTOR, ".loginText"),
]


def _find(driver, selectors, timeout=10):
    for by, sel in selectors:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, sel))
            )
            if el.is_displayed():
                return el
        except Exception:
            continue
    return None


def _is_logged_in(driver):
    try:
        src = driver.page_source
        return any(x in src for x in ['logout','LOGOUT','My Account','myAccount','hi,'])
    except Exception:
        return False


def _do_login(driver, username, password, captcha_solver=None):
    for attempt in range(1, 4):
        try:
            log.info(f"Login attempt {attempt}/3 for user: {username}")
            driver.get(BASE_URL)
            time.sleep(3)

            if _is_logged_in(driver):
                log.info("Already logged in.")
                return True

            # Click LOGIN link
            link = _find(driver, LOGIN_LINK_SELECTORS, timeout=10)
            if link:
                driver.execute_script("arguments[0].click();", link)
                time.sleep(2)

            # Username
            usr = _find(driver, USERNAME_SELECTORS, timeout=15)
            if not usr:
                log.error("Username field not found!")
                time.sleep(2)
                continue
            usr.clear()
            usr.click()
            for ch in username:
                usr.send_keys(ch)
                time.sleep(0.05)

            # Password
            pwd = _find(driver, PASSWORD_SELECTORS, timeout=10)
            if not pwd:
                log.error("Password field not found!")
                continue
            pwd.clear()
            pwd.click()
            for ch in password:
                pwd.send_keys(ch)
                time.sleep(0.05)

            time.sleep(1)

            # CAPTCHA
            if captcha_solver:
                img = _find(driver, CAPTCHA_IMG_SELECTORS, timeout=8)
                if img:
                    try:
                        text = captcha_solver.solve_image_captcha(driver, img)
                        if text:
                            inp = _find(driver, CAPTCHA_INPUT_SELECTORS, timeout=5)
                            if inp:
                                inp.clear()
                                inp.send_keys(text)
                                log.info(f"CAPTCHA: {text}")
                    except Exception as ce:
                        log.warning(f"CAPTCHA error: {ce}")

            time.sleep(0.5)

            # Submit
            btn = _find(driver, LOGIN_BTN_SELECTORS, timeout=10)
            if btn:
                driver.execute_script("arguments[0].click();", btn)
            else:
                pwd.send_keys("\n")

            time.sleep(5)

            if _is_logged_in(driver):
                log.info("Login successful!")
                return True

            src = driver.page_source
            if "invalid" in src.lower() or "incorrect" in src.lower():
                log.error("Wrong credentials!")
                return False

            log.warning(f"Attempt {attempt} failed, retrying...")
            time.sleep(3)

        except Exception as e:
            log.warning(f"Login attempt {attempt} error: {e}")
            time.sleep(3)

    log.error("All login attempts failed.")
    return False


class IRCTCLogin:
    def __init__(self, driver, captcha_solver=None):
        self.driver = driver
        self.captcha_solver = captcha_solver
        self._username = ""
        self._password = ""

    def login(self, username="", password=""):
        """Login with given credentials."""
        # Support calling login() with no args if credentials set via ensure_logged_in
        u = username or self._username
        p = password or self._password
        return _do_login(self.driver, u, p, self.captcha_solver)

    def ensure_logged_in(self, username, password):
        """Called by booking_bot — ensures session is active."""
        self._username = username
        self._password = password
        if _is_logged_in(self.driver):
            log.info("Session already active — skipping login.")
            return True
        return _do_login(self.driver, username, password, self.captcha_solver)

    def is_logged_in(self):
        return _is_logged_in(self.driver)