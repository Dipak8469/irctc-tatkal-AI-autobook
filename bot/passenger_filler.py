# bot/passenger_filler.py — IRCTC Passenger Form Filler (2026)

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from utils.logger import get_logger

log = get_logger("PassengerFiller")


def _scroll_to(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.3)


def _wait_for_passenger_page(driver):
    """Wait until we're on the actual passenger details page."""
    log.info(f"Waiting for passenger page... Current: {driver.current_url}")

    # Keep waiting until URL changes from train-list
    for _ in range(20):
        if "train-list" not in driver.current_url:
            break
        time.sleep(1)

    time.sleep(3)
    log.info(f"Now on: {driver.current_url}")

    # Wait for passenger form elements
    for sel in [
        "//app-passenger",
        "//*[contains(@formcontrolname,'passengerName')]",
        "//*[contains(@formcontrolname,'passenger')]",
        "//div[contains(@class,'passenger-detail')]",
        "//input[@placeholder='Name']",
    ]:
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, sel))
            )
            log.info(f"Passenger form found via: {sel}")
            time.sleep(2)
            return True
        except Exception:
            continue

    time.sleep(4)
    log.warning("Passenger form not confirmed — proceeding anyway")
    return True


def _js_set(driver, el, value):
    """Set input value via JS and trigger Angular change event."""
    driver.execute_script(
        "arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
        "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
        el, str(value)
    )


def _fill_input(driver, xpaths, value):
    """Try multiple xpaths to fill an input field."""
    for xpath in xpaths:
        try:
            els = driver.find_elements(By.XPATH, xpath)
            for el in els:
                if el.is_displayed() and el.is_enabled():
                    _scroll_to(driver, el)
                    try:
                        el.clear()
                        el.click()
                        time.sleep(0.1)
                        el.send_keys(str(value))
                        return True
                    except Exception:
                        _js_set(driver, el, value)
                        return True
        except Exception:
            continue
    return False


def _fill_select(driver, xpaths, value):
    """Try multiple xpaths to select a dropdown value."""
    for xpath in xpaths:
        try:
            els = driver.find_elements(By.XPATH, xpath)
            for el in els:
                if el.is_displayed():
                    _scroll_to(driver, el)
                    try:
                        Select(el).select_by_value(value)
                        return True
                    except Exception:
                        pass
                    try:
                        Select(el).select_by_visible_text(value)
                        return True
                    except Exception:
                        pass
                    # JS fallback
                    driver.execute_script(
                        "var s=arguments[0],v=arguments[1];"
                        "for(var i=0;i<s.options.length;i++){"
                        "if(s.options[i].value==v||s.options[i].text.indexOf(v)>=0){"
                        "s.selectedIndex=i;"
                        "s.dispatchEvent(new Event('change',{bubbles:true}));"
                        "break;}}", el, value
                    )
                    return True
        except Exception:
            continue
    return False


def _tick_checkbox(driver, xpaths, check=True):
    """Check or uncheck a checkbox."""
    for xpath in xpaths:
        try:
            els = driver.find_elements(By.XPATH, xpath)
            for el in els:
                if el.is_displayed():
                    _scroll_to(driver, el)
                    currently = el.is_selected()
                    if currently != check:
                        driver.execute_script("arguments[0].click();", el)
                        time.sleep(0.3)
                    log.info(f"Checkbox {'checked' if check else 'unchecked'}: {xpath}")
                    return True
        except Exception:
            continue
    return False


class PassengerFiller:
    def __init__(self, driver):
        self.driver = driver

    def fill_all_passengers(self, passengers, mobile, insurance=False):
        log.info(f"Filling details for {len(passengers)} passenger(s)...")

        _wait_for_passenger_page(self.driver)

        for i, pax in enumerate(passengers):
            log.info(f"Filling passenger {i+1}: {pax.get('name','')}")
            self._fill_passenger(i, pax)
            time.sleep(0.5)

        self._fill_mobile(mobile)
        self._handle_auto_upgrade()      # ✅ Tick "Consider for Auto Upgrade"
        self._handle_confirm_berths()    # ✅ Tick "Book only if confirm berths"
        self._uncheck_insurance()

        log.info("All passengers filled.")
        return True

    def _fill_passenger(self, idx, pax):
        name    = pax.get('name', '')
        age     = str(pax.get('age', ''))
        gender  = pax.get('gender', 'M')
        berth   = pax.get('berth_pref', 'LB')
        id_type = pax.get('id_type', 'AADHAAR')
        id_num  = pax.get('id_number', '')

        n = idx + 1  # 1-based index for XPath

        # NAME
        filled = _fill_input(self.driver, [
            f"(//input[contains(@formcontrolname,'passengerName')])[{n}]",
            f"(//input[contains(@formcontrolname,'name') and not(@type='hidden')])[{n}]",
            f"(//input[@placeholder='Name'])[{n}]",
            f"(//input[@placeholder='Passenger Name'])[{n}]",
            f"(//app-passenger)[{n}]//input[@type='text'][1]",
            f"(//div[contains(@class,'pax') or contains(@class,'passenger')]//input[@type='text'])[{n}]",
        ], name)
        if not filled:
            log.warning(f"PAX {n}: Name field not found")

        time.sleep(0.2)

        # AGE
        filled = _fill_input(self.driver, [
            f"(//input[contains(@formcontrolname,'passengerAge')])[{n}]",
            f"(//input[contains(@formcontrolname,'age')])[{n}]",
            f"(//input[@placeholder='Age'])[{n}]",
            f"(//app-passenger)[{n}]//input[@type='number']",
            f"(//input[@type='number'])[{n}]",
        ], age)
        if not filled:
            log.warning(f"PAX {n}: Age field not found")

        time.sleep(0.2)

        # GENDER
        filled = _fill_select(self.driver, [
            f"(//select[contains(@formcontrolname,'passengerGender')])[{n}]",
            f"(//select[contains(@formcontrolname,'gender')])[{n}]",
            f"(//app-passenger)[{n}]//select[1]",
        ], gender)
        if not filled:
            log.warning(f"PAX {n}: Gender dropdown not found")

        time.sleep(0.2)

        # BERTH
        _fill_select(self.driver, [
            f"(//select[contains(@formcontrolname,'passengerBerthChoice')])[{n}]",
            f"(//select[contains(@formcontrolname,'berth')])[{n}]",
            f"(//app-passenger)[{n}]//select[2]",
        ], berth)

        time.sleep(0.2)

        # ID TYPE (Tatkal mandatory)
        _fill_select(self.driver, [
            f"(//select[contains(@formcontrolname,'passengerCardType')])[{n}]",
            f"(//select[contains(@formcontrolname,'cardType')])[{n}]",
            f"(//select[contains(@formcontrolname,'CardType')])[{n}]",
            f"(//app-passenger)[{n}]//select[last()]",
        ], id_type)

        time.sleep(0.2)

        # ID NUMBER
        if id_num:
            _fill_input(self.driver, [
                f"(//input[contains(@formcontrolname,'passengerCardNumber')])[{n}]",
                f"(//input[contains(@formcontrolname,'cardNumber')])[{n}]",
                f"(//input[@placeholder='Card Number'])[{n}]",
                f"(//input[@placeholder='Enter ID Number'])[{n}]",
                f"(//app-passenger)[{n}]//input[@type='text'][last()]",
            ], id_num)

        log.info(f"Passenger {n} filled.")

    def _fill_mobile(self, mobile):
        if not mobile:
            return
        filled = _fill_input(self.driver, [
            "//input[@formcontrolname='mobileNumber']",
            "//input[@placeholder='Mobile Number']",
            "//input[@placeholder='Enter Mobile No.']",
            "//input[contains(@formcontrolname,'mobile')]",
            "//input[@type='tel']",
            "//input[@maxlength='10']",
        ], mobile)
        if filled:
            log.info(f"Mobile filled: {mobile}")
        else:
            log.warning("Mobile field not found")

    def _handle_auto_upgrade(self):
        """Tick 'Consider for Auto Upgrade' checkbox."""
        ticked = _tick_checkbox(self.driver, [
            "//input[@type='checkbox'][contains(@formcontrolname,'autoUpgrade')]",
            "//label[contains(text(),'Auto Upgrade')]//preceding-sibling::input",
            "//label[contains(text(),'Auto Upgrade')]/..//input[@type='checkbox']",
            "//*[contains(text(),'Auto Upgrade')]/..//input[@type='checkbox']",
            "//*[contains(text(),'auto upgradation')]/..//input[@type='checkbox']",
            "//p-checkbox[contains(@formcontrolname,'autoUpgrade')]//input",
        ], check=True)
        if ticked:
            log.info("Auto Upgrade checkbox ticked")
        else:
            log.warning("Auto Upgrade checkbox not found")

    def _handle_confirm_berths(self):
        """Tick 'Book only if confirm berths are allocated'."""
        ticked = _tick_checkbox(self.driver, [
            "//input[@type='checkbox'][contains(@formcontrolname,'confirmBerth')]",
            "//label[contains(text(),'confirm berth')]//preceding-sibling::input",
            "//label[contains(text(),'Confirm Berth')]/..//input[@type='checkbox']",
            "//*[contains(text(),'confirm berth')]/..//input[@type='checkbox']",
            "//*[contains(text(),'confirmed berth')]/..//input[@type='checkbox']",
            "//p-checkbox[contains(@formcontrolname,'confirmBerth')]//input",
        ], check=True)
        if ticked:
            log.info("Confirm Berths checkbox ticked")
        else:
            log.warning("Confirm Berths checkbox not found")

    def _uncheck_insurance(self):
        """Uncheck travel insurance."""
        _tick_checkbox(self.driver, [
            "//input[@type='checkbox'][contains(@formcontrolname,'insurance')]",
            "//*[contains(text(),'Insurance')]/..//input[@type='checkbox']",
            "//label[contains(text(),'Insurance')]/..//input[@type='checkbox']",
        ], check=False)

    def click_confirm_booking(self):
        for sel in [
            "//button[contains(text(),'Continue')]",
            "//button[contains(text(),'CONTINUE')]",
            "//button[contains(text(),'Confirm')]",
            "//button[contains(text(),'NEXT')]",
            "//button[contains(text(),'Next')]",
            "//button[@type='submit']",
        ]:
            try:
                btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, sel))
                )
                _scroll_to(self.driver, btn)
                self.driver.execute_script("arguments[0].click();", btn)
                log.info(f"Confirm clicked")
                time.sleep(3)
                return True
            except Exception:
                continue
        log.warning("Confirm button not found")
        return False