# bot/payment.py — Handles auto-payment on IRCTC

import time
import random
from utils.logger import get_logger
from utils.encryption import secure_store
from config.settings import PAYMENT_TIMEOUT, CLICK_DELAY

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

log = get_logger("Payment")


class PaymentHandler:
    """
    Handles IRCTC payment flow.
    Supports: UPI, Debit/Credit Card, Net Banking, IRCTC Wallet.
    """

    def __init__(self, driver, payment_config: dict):
        """
        payment_config: {
            'method': 'upi' | 'card' | 'netbanking' | 'wallet',
            'upi_id': '...',
            'card_number': '...',
            'card_name': '...',
            'card_expiry': 'MM/YY',
            'card_cvv': '...',
            'bank': '...',
            'nb_user': '...',
            'nb_pass': '...'
        }
        """
        self.driver = driver
        self.wait = WebDriverWait(driver, PAYMENT_TIMEOUT)
        self.short_wait = WebDriverWait(driver, 20)
        self.config = payment_config
        self.actions = ActionChains(driver)

    # ─────────────────────────────────────────────
    #  Public: execute payment
    # ─────────────────────────────────────────────
    def execute(self) -> bool:
        """Main payment execution. Returns True if payment initiated."""
        method = self.config.get("method", "upi").lower()
        log.info(f"Starting payment via: {method.upper()}")

        try:
            # Wait for payment page
            self._wait_for_payment_page()

            dispatch = {
                "upi":        self._pay_upi,
                "card":       self._pay_card,
                "netbanking": self._pay_netbanking,
                "nb":         self._pay_netbanking,
                "wallet":     self._pay_wallet,
            }

            handler = dispatch.get(method)
            if not handler:
                log.error(f"Unknown payment method: {method}")
                return False

            result = handler()
            if result:
                log.info("✅ Payment step completed — awaiting confirmation.")
            else:
                log.error("Payment step failed.")
            return result

        except Exception as e:
            log.error(f"Payment execution failed: {e}")
            return False

    # ─────────────────────────────────────────────
    #  UPI Payment
    # ─────────────────────────────────────────────
    def _pay_upi(self) -> bool:
        upi_id = self.config.get("upi_id", "")
        if not upi_id:
            log.error("UPI ID not provided!")
            return False

        try:
            # Select UPI option
            self._click_payment_option(["UPI", "Bhim", "GPay", "PhonePe", "BHIM UPI"])

            # Enter UPI ID
            upi_field = self.short_wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    "input[placeholder*='UPI'], input[name*='upi'], input[id*='upi']"
                ))
            )
            upi_field.clear()
            upi_field.send_keys(upi_id)
            time.sleep(0.5)

            # Click Verify/Pay button
            self._click_button_by_text(["Verify", "Pay Now", "Proceed", "Submit"])
            log.info(f"UPI payment initiated for: {upi_id}")
            log.info("⚠️  Please approve the UPI payment request on your phone!")
            return True

        except Exception as e:
            log.error(f"UPI payment failed: {e}")
            return False

    # ─────────────────────────────────────────────
    #  Card Payment
    # ─────────────────────────────────────────────
    def _pay_card(self) -> bool:
        cfg = self.config
        if not all([cfg.get("card_number"), cfg.get("card_cvv")]):
            log.error("Card details incomplete!")
            return False

        try:
            # Select Debit/Credit card option
            self._click_payment_option([
                "Debit Card", "Credit Card", "Visa", "Mastercard", "RuPay"
            ])
            time.sleep(1)

            # Card Number
            card_num = cfg["card_number"].replace(" ", "").replace("-", "")
            self._fill_field_by_attrs(
                ["cardNumber", "card_number", "cardNo", "cardnumber"],
                card_num
            )

            # Cardholder Name
            if cfg.get("card_name"):
                self._fill_field_by_attrs(
                    ["cardName", "nameOnCard", "card_name", "holdername"],
                    cfg["card_name"]
                )

            # Expiry
            if cfg.get("card_expiry"):
                expiry = cfg["card_expiry"].replace("/", "")
                self._fill_field_by_attrs(
                    ["expiry", "expiryDate", "cardExpiry", "exp_date"],
                    expiry
                )

            # CVV
            self._fill_field_by_attrs(
                ["cvv", "CVV", "cardCvv", "securityCode"],
                cfg["card_cvv"]
            )

            # Pay button
            self._click_button_by_text(["Pay Now", "Make Payment", "Proceed", "Submit"])
            log.info("Card payment submitted.")
            log.info("⚠️  Check your phone for OTP/3D-Secure verification!")
            return True

        except Exception as e:
            log.error(f"Card payment failed: {e}")
            return False

    # ─────────────────────────────────────────────
    #  Net Banking
    # ─────────────────────────────────────────────
    def _pay_netbanking(self) -> bool:
        cfg = self.config

        try:
            # Select Net Banking
            self._click_payment_option(["Net Banking", "NetBanking", "Internet Banking"])
            time.sleep(1)

            # Select bank
            if cfg.get("bank"):
                bank_opts = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "select[name*='bank'] option, .bank-list li, .bank-option"
                )
                for opt in bank_opts:
                    if cfg["bank"].lower() in opt.text.lower():
                        opt.click()
                        break

            # Click proceed
            self._click_button_by_text(["Pay Now", "Proceed", "Continue"])
            log.info(f"Net Banking: redirecting to {cfg.get('bank', 'bank')} page.")
            log.info("⚠️  You may need to manually complete 2FA on your bank's page.")
            return True

        except Exception as e:
            log.error(f"Net Banking payment failed: {e}")
            return False

    # ─────────────────────────────────────────────
    #  IRCTC Wallet
    # ─────────────────────────────────────────────
    def _pay_wallet(self) -> bool:
        try:
            self._click_payment_option([
                "IRCTC Wallet", "iWallet", "Wallet", "IRCTC iMudra"
            ])
            time.sleep(0.5)
            self._click_button_by_text(["Pay Now", "Proceed", "Pay"])
            log.info("IRCTC Wallet payment submitted.")
            return True
        except Exception as e:
            log.error(f"Wallet payment failed: {e}")
            return False

    # ─────────────────────────────────────────────
    #  Wait for PNR
    # ─────────────────────────────────────────────
    def wait_for_pnr(self, timeout: int = 120) -> str:
        """
        Wait for the booking confirmation page and extract PNR.
        Returns PNR string or empty string on failure.
        """
        log.info("Waiting for booking confirmation and PNR...")
        wait = WebDriverWait(self.driver, timeout)

        try:
            # PNR usually appears as 10-digit number on confirmation page
            pnr_element = wait.until(
                EC.presence_of_element_located((By.XPATH,
                    "//*[contains(text(), 'PNR') or contains(@class, 'pnr')]"
                    "[string-length(normalize-space(text())) >= 10]"
                ))
            )

            text = pnr_element.text.strip()
            # Extract 10-digit PNR
            import re
            pnr_match = re.search(r'\b\d{10}\b', text)
            if pnr_match:
                pnr = pnr_match.group()
                log.info(f"🎉 PNR extracted: {pnr}")
                return pnr

            log.warning(f"PNR element found but number not extracted: {text}")
            return text

        except TimeoutException:
            # Try alternative selectors
            try:
                pnr_el = self.driver.find_element(
                    By.CSS_SELECTOR, ".pnr-no, #pnrNo, [class*='pnr']"
                )
                return pnr_el.text.strip()
            except Exception:
                pass

            log.error("PNR not found within timeout.")
            return ""

    # ─────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────
    def _wait_for_payment_page(self):
        """Wait for IRCTC payment gateway to load."""
        try:
            self.short_wait.until(
                EC.presence_of_element_located((By.XPATH,
                    "//*[contains(text(),'Payment') or contains(text(),'payment')]"
                ))
            )
            time.sleep(1.5)
            log.info("Payment page loaded.")
        except TimeoutException:
            log.warning("Payment page detection timeout — proceeding anyway.")

    def _click_payment_option(self, labels: list):
        """Click a payment option tab/radio by label text."""
        for label in labels:
            try:
                # Try by text
                elements = self.driver.find_elements(
                    By.XPATH,
                    f"//*[contains(text(), '{label}')]"
                )
                for el in elements:
                    if el.is_displayed() and el.is_enabled():
                        el.click()
                        time.sleep(0.5)
                        log.info(f"Payment option selected: {label}")
                        return
            except Exception:
                continue

        log.warning(f"Could not select payment option from: {labels}")

    def _click_button_by_text(self, labels: list):
        """Click a button by its text content."""
        for label in labels:
            try:
                btn = self.driver.find_element(
                    By.XPATH,
                    f"//button[contains(text(), '{label}')] | "
                    f"//input[@value='{label}']"
                )
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    time.sleep(0.5)
                    return
            except Exception:
                continue

    def _fill_field_by_attrs(self, attr_names: list, value: str):
        """Fill input field searching by common name/id patterns."""
        for attr in attr_names:
            for attr_type in ["name", "id", "formcontrolname", "placeholder"]:
                try:
                    field = self.driver.find_element(
                        By.CSS_SELECTOR,
                        f"input[{attr_type}*='{attr}']"
                    )
                    if field.is_displayed():
                        field.clear()
                        field.send_keys(value)
                        return
                except Exception:
                    continue
