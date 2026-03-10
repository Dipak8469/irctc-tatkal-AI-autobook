# bot/train_search.py — IRCTC Train Search (2026)

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from utils.logger import get_logger
from config.settings import BASE_URL

log = get_logger("TrainSearch")

FROM_SELECTORS = [
    (By.XPATH, "//input[@placeholder='From' or @placeholder='FROM *']"),
    (By.XPATH, "//p-autocomplete[@formcontrolname='origin']//input"),
    (By.XPATH, "(//input[@role='searchbox'])[1]"),
]
TO_SELECTORS = [
    (By.XPATH, "//input[@placeholder='To' or @placeholder='TO *']"),
    (By.XPATH, "//p-autocomplete[@formcontrolname='destination']//input"),
    (By.XPATH, "(//input[@role='searchbox'])[2]"),
]
DATE_SELECTORS = [
    (By.XPATH, "//input[@placeholder='Date of Journey' or @placeholder='DD/MM/YYYY']"),
    (By.XPATH, "//p-calendar//input"),
    (By.CSS_SELECTOR, "p-calendar input"),
]
SEARCH_BTN_SELECTORS = [
    (By.XPATH, "//button[contains(text(),'Search')]"),
    (By.XPATH, "//button[normalize-space()='Search']"),
    (By.CSS_SELECTOR, "button.search_btn"),
    (By.XPATH, "//button[@type='submit']"),
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


def _scroll_to(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.3)


def _type_station(driver, field, code):
    """Type station code and pick from autocomplete."""
    _scroll_to(driver, field)
    driver.execute_script("arguments[0].click();", field)
    time.sleep(0.3)
    field.clear()
    for ch in code:
        field.send_keys(ch)
        time.sleep(0.12)
    time.sleep(2.5)
    # Pick first matching suggestion
    for sel in [
        f"//span[contains(text(),'{code.upper()}')]",
        "//ul[contains(@class,'ui-autocomplete-list')]//li[1]",
        "//div[@role='option'][1]",
        "//li[contains(@class,'ui-autocomplete-list-item')][1]",
    ]:
        try:
            sugg = WebDriverWait(driver, 4).until(
                EC.element_to_be_clickable((By.XPATH, sel))
            )
            driver.execute_script("arguments[0].click();", sugg)
            log.info(f"Station selected: {code}")
            time.sleep(0.5)
            return
        except Exception:
            continue
    field.send_keys("\n")
    time.sleep(0.5)


class TrainSearch:
    def __init__(self, driver):
        self.driver = driver

    def fill_search_form(self, from_station, to_station, travel_date, quota="TQ"):
        log.info(f"Filling search: {from_station} -> {to_station} | {travel_date} | {quota}")

        if "train-search" not in self.driver.current_url:
            self.driver.get(BASE_URL)
            time.sleep(4)

        # Scroll to top first
        self.driver.execute_script("window.scrollTo(0,0);")
        time.sleep(1)

        # FROM
        f = _find(self.driver, FROM_SELECTORS, timeout=15)
        if not f:
            raise Exception("From field not found")
        _type_station(self.driver, f, from_station)
        time.sleep(1)

        # TO
        t = _find(self.driver, TO_SELECTORS, timeout=10)
        if not t:
            raise Exception("To field not found")
        _type_station(self.driver, t, to_station)
        time.sleep(1)

        # DATE
        d = _find(self.driver, DATE_SELECTORS, timeout=10)
        if d:
            _scroll_to(self.driver, d)
            driver = self.driver
            driver.execute_script("arguments[0].click();", d)
            time.sleep(0.5)
            d.clear()
            driver.execute_script("arguments[0].value='';", d)
            d.send_keys(travel_date)
            time.sleep(0.5)
            driver.execute_script("document.body.click();")
            time.sleep(1)
            log.info(f"Date set: {travel_date}")

        # QUOTA
        try:
            qdd = self.driver.find_element(
                By.XPATH, "//p-dropdown[@formcontrolname='journeyQuota']"
            )
            _scroll_to(self.driver, qdd)
            self.driver.execute_script("arguments[0].click();", qdd)
            time.sleep(1)
            for qsel in [
                f"//li[@aria-label='{quota}']",
                f"//li[contains(.,'{quota}')]",
                f"//span[text()='{quota}']",
            ]:
                try:
                    opt = self.driver.find_element(By.XPATH, qsel)
                    self.driver.execute_script("arguments[0].click();", opt)
                    log.info(f"Quota set: {quota}")
                    break
                except Exception:
                    continue
        except Exception:
            log.warning("Quota dropdown not found — using default")

        return True

    def submit_search(self):
        time.sleep(1)
        btn = _find(self.driver, SEARCH_BTN_SELECTORS, timeout=10)
        if btn:
            _scroll_to(self.driver, btn)
            self.driver.execute_script("arguments[0].click();", btn)
            log.info("Search submitted")
            time.sleep(6)
            return True
        raise Exception("Search button not found")

    def select_train_and_class(self, train_number, travel_class, quota="TQ"):
        log.info(f"Selecting train {train_number}, class {travel_class}")

        # Wait for results
        WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 "//div[contains(@class,'train-info')] | "
                 "//app-train-avl-enq | "
                 "//div[contains(@class,'train-list')]")
            )
        )
        time.sleep(2)
        self.driver.execute_script("window.scrollTo(0,0);")
        time.sleep(1)

        # Find specific train or use first available
        train_found = False
        try:
            rows = self.driver.find_elements(
                By.XPATH,
                "//div[contains(@class,'train-info')] | //app-train-avl-enq"
            )
            for row in rows:
                if train_number in row.text:
                    _scroll_to(self.driver, row)
                    train_found = True
                    log.info(f"Train {train_number} found")
                    break
            if not train_found:
                log.warning(f"Train {train_number} not in results — using first")
                if rows:
                    _scroll_to(self.driver, rows[0])
        except Exception:
            pass

        time.sleep(1)

        # Click class button (e.g. 3A, SL, 2A)
        for sel in [
            f"//div[contains(@class,'pre-avl')][.//strong[normalize-space()='{travel_class}']]",
            f"//td[.//strong[normalize-space()='{travel_class}']]",
            f"//strong[normalize-space()='{travel_class}']",
            f"//div[contains(@class,'col-xs') and contains(.,'{travel_class}')]//strong",
        ]:
            try:
                el = self.driver.find_element(By.XPATH, sel)
                _scroll_to(self.driver, el)
                self.driver.execute_script("arguments[0].click();", el)
                log.info(f"Class {travel_class} clicked")
                time.sleep(2)
                break
            except Exception:
                continue
        else:
            raise Exception(f"Class {travel_class} button not found")

        # Wait for availability to load and click Book Now
        time.sleep(2)
        for sel in [
            "//button[contains(text(),'Book Now')]",
            "//button[normalize-space()='Book Now']",
            "//a[contains(text(),'Book Now')]",
            "//span[contains(text(),'Book Now')]",
        ]:
            try:
                btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, sel))
                )
                _scroll_to(self.driver, btn)
                self.driver.execute_script("arguments[0].click();", btn)
                log.info("Book Now clicked")
                time.sleep(4)
                # Wait for navigation away from train-list
                try:
                    WebDriverWait(self.driver, 15).until(
                        lambda d: "train-list" not in d.current_url
                    )
                    log.info(f"Navigated to: {self.driver.current_url}")
                except Exception:
                    log.warning("URL did not change after Book Now — may need login")
                return True
            except Exception:
                continue

        log.warning("Book Now not found — may have auto-advanced")
        return True