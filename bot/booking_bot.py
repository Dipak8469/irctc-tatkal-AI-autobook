# bot/booking_bot.py — Main orchestrator: wires all modules together

import time
import datetime
import threading
from utils.logger import get_logger
from utils.encryption import secure_store
from utils.notifier import notifier
from bot.driver import create_driver, safe_quit
from bot.login import IRCTCLogin
from bot.train_search import TrainSearch
from bot.passenger_filler import PassengerFiller
from bot.payment import PaymentHandler
from bot.scheduler import TatkalScheduler
from config.settings import MAX_RETRIES, POST_SUBMIT_WAIT

log = get_logger("BookingBot")


class BookingJob:
    """
    Data container for a single booking job.
    All required info to complete one IRCTC Tatkal booking.
    """
    def __init__(self):
        # Journey
        self.from_station   = ""
        self.to_station     = ""
        self.travel_date    = ""     # DD/MM/YYYY
        self.train_number   = ""
        self.train_class    = "3A"
        self.quota          = "TQ"

        # Scheduling
        self.booking_date   = None   # datetime.date (D-1)
        self.trigger_hour   = 10
        self.trigger_minute = 0
        self.pre_login_secs = 120

        # Passengers
        self.passengers     = []     # list of dicts
        self.mobile         = ""
        self.berth_pref1    = "LB"
        self.berth_pref2    = ""
        self.insurance      = False

        # Payment
        self.payment        = {}     # method + credentials

        # IRCTC account
        self.username       = ""
        self.password       = ""

        # Fallbacks
        self.alt_quota      = None
        self.alt_train      = None

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()
                if k not in ("password",)}  # Never log password


class IRCTCBookingBot:
    """
    Main IRCTC Tatkal AutoBook bot.
    Usage:
        bot = IRCTCBookingBot()
        bot.load_job(job)
        bot.arm()   # starts scheduler, blocks until done
    """

    def __init__(self):
        self.driver = None
        self.job: BookingJob = None
        self.scheduler = TatkalScheduler()
        self.result = {"success": False, "pnr": "", "error": ""}
        self.status_callbacks = []
        self._booking_thread = None

    # ─────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────
    def load_job(self, job: BookingJob):
        """Load a booking job."""
        self.job = job
        # Store credentials in secure memory
        secure_store.set("username", job.username)
        secure_store.set("password", job.password)
        log.info(f"Job loaded: {job.to_dict()}")

    def add_status_callback(self, cb):
        """Register a callback for status updates: cb(event_dict)."""
        self.status_callbacks.append(cb)

    def arm(self, blocking: bool = True):
        """
        Arm the bot. Waits for the scheduled time then executes booking.
        blocking=True: current thread waits.
        blocking=False: runs in background thread.
        """
        if not self.job:
            log.error("No job loaded! Call load_job() first.")
            return

        log.info("🤖 BOT ARMED — waiting for scheduled time...")
        self._emit("armed", "Bot armed — countdown started.")

        if blocking:
            self._run_scheduler()
        else:
            self._booking_thread = threading.Thread(
                target=self._run_scheduler, daemon=True
            )
            self._booking_thread.start()

    def disarm(self):
        """Stop the bot before it fires."""
        self.scheduler.stop()
        log.info("Bot disarmed.")

    def run_now(self):
        """
        Skip the scheduler and run the booking immediately.
        Useful for testing or when Tatkal window is already open.
        """
        log.info("Running booking immediately (bypassing scheduler)...")
        self._execute_booking()

    # ─────────────────────────────────────────────
    #  Scheduler
    # ─────────────────────────────────────────────
    def _run_scheduler(self):
        job = self.job

        # Build trigger datetime
        bd = job.booking_date or (
            datetime.date.today() if datetime.datetime.now().hour < job.trigger_hour
            else datetime.date.today()
        )
        trigger_dt = datetime.datetime(
            bd.year, bd.month, bd.day,
            job.trigger_hour, job.trigger_minute, 0
        )

        log.info(f"Booking will trigger at: {trigger_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        self._emit("scheduled", f"Trigger: {trigger_dt.strftime('%H:%M:%S')} on {bd}")

        self.scheduler.set_callbacks(
            on_prelogin=self._pre_login_phase,
            on_trigger=self._execute_booking,
            on_status=lambda s: self._emit(s["status"], s["message"])
        )

        self.scheduler.wait_and_trigger(trigger_dt, job.pre_login_secs)

    # ─────────────────────────────────────────────
    #  Pre-login phase (fires ~120s before)
    # ─────────────────────────────────────────────
    def _pre_login_phase(self):
        """Login early, keep session warm."""
        log.info("🔑 Pre-login phase — warming up session...")
        self._emit("pre_login", "Logging in early to warm session...")

        try:
            self.driver = create_driver()
            login_handler = IRCTCLogin(self.driver)
            success = login_handler.login()

            if success:
                log.info("✅ Pre-login successful — session warm.")
                self._emit("logged_in", "Session active and warm.")
                # Navigate to train search page to have it ready
                from config.settings import BASE_URL
                self.driver.get(BASE_URL)
                time.sleep(2)
            else:
                log.error("Pre-login failed!")
                self._emit("login_failed", "Login failed — will retry at trigger.")

        except Exception as e:
            log.error(f"Pre-login phase error: {e}")
            self._emit("error", f"Pre-login error: {e}")

    # ─────────────────────────────────────────────
    #  Main booking execution
    # ─────────────────────────────────────────────
    def _execute_booking(self):
        """Full booking flow executed at trigger time."""
        job = self.job
        log.info("🚀 BOOKING EXECUTION STARTED")
        self._emit("booking_start", "Booking sequence initiated!")

        try:
            # Ensure driver is running
            if not self.driver:
                self.driver = create_driver()

            login_hdl = IRCTCLogin(self.driver)
            search_hdl = TrainSearch(self.driver)
            pax_hdl    = PassengerFiller(self.driver)
            pay_hdl    = PaymentHandler(self.driver, job.payment)

            # ── Step 1: Ensure logged in ──
            self._emit("step", "Step 1: Verifying login...")
            if not login_hdl.ensure_logged_in(job.username, job.password):
                raise Exception("Login failed at booking time!")
            log.info("✅ Step 1: Login OK")

            # ── Step 2: Search train ──
            self._emit("step", "Step 2: Searching for train...")
            ok = search_hdl.fill_search_form(
                job.from_station, job.to_station,
                job.travel_date, job.quota
            )
            if not ok:
                raise Exception("Train search form fill failed!")

            ok = search_hdl.submit_search()
            if not ok:
                raise Exception("Train search submit failed!")
            log.info("✅ Step 2: Search submitted")

            # ── Step 3: Select train + class ──
            self._emit("step", f"Step 3: Selecting train {job.train_number} class {job.train_class}...")
            ok = search_hdl.select_train_and_class(
                job.train_number, job.train_class, job.quota
            )
            if not ok:
                # Try alternate quota if configured
                if job.alt_quota:
                    log.warning(f"Trying alternate quota: {job.alt_quota}")
                    ok = search_hdl.select_train_and_class(
                        job.train_number, job.train_class, job.alt_quota
                    )
                if not ok:
                    raise Exception(f"Train {job.train_number} / class {job.train_class} not available!")
            log.info("✅ Step 3: Train and class selected")

            # ── Step 4: Fill passengers ──
            self._emit("step", "Step 4: Filling passenger details...")
            ok = pax_hdl.fill_all_passengers(
                job.passengers, job.mobile, job.insurance
            )
            if not ok:
                raise Exception("Passenger details fill failed!")
            log.info("✅ Step 4: Passengers filled")

            # ── Step 5: Confirm booking (pre-payment) ──
            self._emit("step", "Step 5: Confirming booking...")
            ok = pax_hdl.click_confirm_booking()
            if not ok:
                raise Exception("Booking confirmation click failed!")
            time.sleep(POST_SUBMIT_WAIT)
            log.info("✅ Step 5: Booking confirmed — going to payment")

            # ── Step 6: Payment ──
            self._emit("step", f"Step 6: Paying via {job.payment.get('method', '?').upper()}...")
            ok = pay_hdl.execute()
            if not ok:
                raise Exception("Payment execution failed!")
            log.info("✅ Step 6: Payment initiated")

            # ── Step 7: Wait for PNR ──
            self._emit("step", "Step 7: Awaiting PNR confirmation...")
            pnr = pay_hdl.wait_for_pnr(timeout=180)

            if pnr:
                self.result = {"success": True, "pnr": pnr, "error": ""}
                log.info(f"🎉 BOOKING SUCCESS! PNR: {pnr}")
                self._emit("success", f"BOOKED! PNR: {pnr}")
                notifier.booking_success(
                    pnr=pnr,
                    train=job.train_number,
                    from_st=job.from_station,
                    to_st=job.to_station,
                    travel_date=job.travel_date,
                    passengers=job.passengers
                )
            else:
                log.warning("Payment may have succeeded but PNR not captured.")
                log.warning("Please check irctc.co.in for booking status.")
                self._emit("warning", "Payment done — check IRCTC for PNR manually.")

        except Exception as e:
            self.result = {"success": False, "pnr": "", "error": str(e)}
            log.error(f"❌ BOOKING FAILED: {e}")
            self._emit("error", f"Booking failed: {e}")
            notifier.booking_failed(str(e))
            # Retry
            self._maybe_retry()

    # ─────────────────────────────────────────────
    #  Retry logic
    # ─────────────────────────────────────────────
    def _maybe_retry(self, attempt: int = 1):
        if attempt >= MAX_RETRIES:
            log.error(f"All {MAX_RETRIES} booking attempts exhausted.")
            return
        log.warning(f"Retrying booking ({attempt+1}/{MAX_RETRIES})...")
        self._emit("retry", f"Retrying ({attempt+1}/{MAX_RETRIES})...")
        time.sleep(3)
        self._execute_booking()

    # ─────────────────────────────────────────────
    #  Status emitter
    # ─────────────────────────────────────────────
    def _emit(self, event: str, message: str):
        data = {
            "event": event,
            "message": message,
            "time": datetime.datetime.now().isoformat()
        }
        for cb in self.status_callbacks:
            try:
                cb(data)
            except Exception:
                pass

    def cleanup(self):
        """Release resources."""
        safe_quit(self.driver)
        secure_store.clear()
        log.info("Bot cleanup complete.")
