# utils/captcha_solver.py — Solves IRCTC CAPTCHA via OCR or 2Captcha API

import os
import time
import base64
import requests
import numpy as np
from io import BytesIO
from PIL import Image, ImageFilter, ImageEnhance
from utils.logger import get_logger
from config.settings import CAPTCHA_API_KEY, USE_LOCAL_OCR

log = get_logger("CaptchaSolver")

# ── Try importing optional libs ──
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    log.warning("OpenCV not available — using PIL-only preprocessing.")

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    log.warning("Pytesseract not available — OCR disabled.")


class CaptchaSolver:
    """
    Multi-strategy CAPTCHA solver:
    1. 2Captcha API  (most reliable, costs ~$0.001/captcha)
    2. Local Tesseract OCR  (free, ~70% accuracy on IRCTC)
    3. Manual fallback  (asks user to type it)
    """

    def __init__(self, api_key: str = CAPTCHA_API_KEY):
        self.api_key = api_key
        self.use_local = USE_LOCAL_OCR or not api_key
        log.info(f"CaptchaSolver init — mode: {'local OCR' if self.use_local else '2Captcha API'}")

    # ─────────────────────────────────────────────
    #  Main entry point
    # ─────────────────────────────────────────────
    def solve(self, image_source) -> str:
        """
        Solve CAPTCHA from:
        - PIL Image object
        - base64 string
        - file path
        - bytes
        Returns solved text string.
        """
        img = self._load_image(image_source)
        img = self._preprocess(img)

        if not self.use_local and self.api_key:
            result = self._solve_2captcha(img)
        elif TESSERACT_AVAILABLE:
            result = self._solve_ocr(img)
        else:
            result = self._solve_manual()

        result = result.strip().replace(" ", "")
        log.info(f"CAPTCHA solved: '{result}'")
        return result

    def solve_from_element(self, driver, captcha_element) -> str:
        """Solve CAPTCHA directly from a Selenium WebElement (screenshot)."""
        png = captcha_element.screenshot_as_png
        img = Image.open(BytesIO(png))
        return self.solve(img)

    # ─────────────────────────────────────────────
    #  2Captcha API
    # ─────────────────────────────────────────────
    def _solve_2captcha(self, img: Image.Image) -> str:
        log.info("Sending CAPTCHA to 2Captcha API...")
        b64 = self._img_to_base64(img)

        # Submit CAPTCHA
        submit_resp = requests.post("http://2captcha.com/in.php", data={
            "key":    self.api_key,
            "method": "base64",
            "body":   b64,
            "json":   1
        }, timeout=30)

        if submit_resp.json().get("status") != 1:
            log.error(f"2Captcha submit failed: {submit_resp.text}")
            return self._solve_manual()

        captcha_id = submit_resp.json()["request"]
        log.info(f"2Captcha job ID: {captcha_id} — polling for result...")

        # Poll for result
        for attempt in range(20):
            time.sleep(3)
            result_resp = requests.get("http://2captcha.com/res.php", params={
                "key":    self.api_key,
                "action": "get",
                "id":     captcha_id,
                "json":   1
            }, timeout=15)
            data = result_resp.json()
            if data.get("status") == 1:
                log.info(f"2Captcha result: {data['request']}")
                return data["request"]
            elif data.get("request") != "CAPCHA_NOT_READY":
                log.error(f"2Captcha error: {data}")
                break

        log.warning("2Captcha timed out — falling back to OCR/manual.")
        return self._solve_ocr(img) if TESSERACT_AVAILABLE else self._solve_manual()

    # ─────────────────────────────────────────────
    #  Local OCR (Tesseract)
    # ─────────────────────────────────────────────
    def _solve_ocr(self, img: Image.Image) -> str:
        log.info("Solving CAPTCHA with local Tesseract OCR...")
        # Try multiple preprocessing strategies and pick best
        candidates = []
        for strategy in [self._preprocess_v1, self._preprocess_v2, self._preprocess_v3]:
            try:
                processed = strategy(img.copy())
                text = pytesseract.image_to_string(
                    processed,
                    config="--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
                ).strip()
                if 4 <= len(text) <= 8:
                    candidates.append(text)
            except Exception as e:
                log.debug(f"OCR strategy failed: {e}")

        if candidates:
            result = max(set(candidates), key=candidates.count)
            log.info(f"OCR candidates: {candidates} → chose: {result}")
            return result

        log.warning("OCR failed — falling back to manual input.")
        return self._solve_manual()

    # ─────────────────────────────────────────────
    #  Preprocessing Strategies
    # ─────────────────────────────────────────────
    def _preprocess(self, img: Image.Image) -> Image.Image:
        """Basic preprocessing applied before all solvers."""
        img = img.convert("L")  # Grayscale
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        return img

    def _preprocess_v1(self, img: Image.Image) -> Image.Image:
        """High contrast threshold."""
        img = img.point(lambda x: 0 if x < 140 else 255)
        return img

    def _preprocess_v2(self, img: Image.Image) -> Image.Image:
        """Enhance + denoise."""
        img = ImageEnhance.Contrast(img).enhance(3.0)
        img = img.filter(ImageFilter.MedianFilter(3))
        img = img.point(lambda x: 0 if x < 160 else 255)
        return img

    def _preprocess_v3(self, img: Image.Image) -> Image.Image:
        """OpenCV adaptive threshold."""
        if not CV2_AVAILABLE:
            return self._preprocess_v1(img)
        arr = np.array(img)
        thresh = cv2.adaptiveThreshold(
            arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        return Image.fromarray(thresh)

    # ─────────────────────────────────────────────
    #  Manual Fallback
    # ─────────────────────────────────────────────
    def _solve_manual(self) -> str:
        """Show CAPTCHA image and ask user to type it."""
        log.warning("Manual CAPTCHA input required!")
        return input(">>> Please type the CAPTCHA text: ").strip()

    # ─────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────
    def _load_image(self, source) -> Image.Image:
        if isinstance(source, Image.Image):
            return source
        elif isinstance(source, bytes):
            return Image.open(BytesIO(source))
        elif isinstance(source, str):
            if os.path.isfile(source):
                return Image.open(source)
            else:
                return Image.open(BytesIO(base64.b64decode(source)))
        raise ValueError(f"Unsupported image source type: {type(source)}")

    def _img_to_base64(self, img: Image.Image) -> str:
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
