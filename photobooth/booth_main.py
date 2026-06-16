"""
Photobooth runtime — asyncio entry point for Raspberry Pi 4B.
Console entry point: ``photobooth-run``.

Runtime config is read from environment variables (typically loaded by
systemd via ``EnvironmentFile=-/etc/ctp/booth.env``). Each key falls back
to the hardcoded default below, so an empty/missing env file is safe.
"""

import asyncio
import logging
import os
import random
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

import board

from photobooth import RPi, Uploader, state_store
from photobooth.health import HealthMonitor
from photobooth.logging_config import setup_logging
from photobooth.strip import PhotoStrip
from photobooth.template_loader import LocalTemplateLoader

# Phase 4 health probes are imported lazily inside ``_startup`` so the
# booth_main module surface stays importable on non-Pi dev machines
# (where the transitive ``escpos`` / ``neopixel`` / ``board`` deps
# aren't always installed). Tests patch these names on the
# ``booth_main`` module after import — keep them as module-level
# attributes so ``monkeypatch.setattr`` works the same way it does for
# pre-Phase-4 names.
probe_camera_available = None
probe_internet_available = None
probe_local_network = None
probe_neopixel_available = None
probe_printer_available = None
probe_web_available = None


def _load_probes() -> None:
    """Resolve probe symbols from their home modules.

    Called by ``_startup`` so a fresh process binds the real probes;
    tests that ``monkeypatch.setattr`` the names on this module override
    these bindings without going through ``_load_probes``.
    """
    global probe_camera_available, probe_internet_available
    global probe_local_network, probe_neopixel_available
    global probe_printer_available, probe_web_available

    if probe_camera_available is None:
        from photobooth.camera import probe_camera_available as _camera

        probe_camera_available = _camera
    if probe_internet_available is None:
        from photobooth.booth import probe_internet_available as _www

        probe_internet_available = _www
    if probe_local_network is None:
        from photobooth.booth import probe_local_network as _lan

        probe_local_network = _lan
    if probe_neopixel_available is None:
        from photobooth.neopixel import probe_neopixel_available as _np

        probe_neopixel_available = _np
    if probe_printer_available is None:
        from photobooth.printer import probe_printer_available as _print

        probe_printer_available = _print
    if probe_web_available is None:
        from photobooth.booth import probe_web_available as _web

        probe_web_available = _web


logger = logging.getLogger(__name__)

# --- Hardware / storage ---
S3_BUCKET = os.environ.get("BOOTH_S3_BUCKET", "public.capturingtimephoto.net")
BOOTH_DIR = os.environ.get("BOOTH_IMAGE_DIR", "/opt/booth_images")
CAMERA_MODEL = os.environ.get("BOOTH_CAMERA_MODEL", "Canon EOS 800D")
CAMERA_STARTUP_CONFIG = {
    "autoexposuremode": 3,  # Manual — prevents built-in flash from auto-firing
}
MAX_PRINTS = int(os.environ.get("BOOTH_MAX_PRINTS", "3"))

# --- Startup health-probe timeouts (v0.5.0 Phase 4) ---
# Required components raise on miss so systemd can restart the service.
# Optional components log + continue (degraded mode).
HEALTH_TIMEOUT_WEB = 30.0  # Django subprocess we just spawned — fast.
HEALTH_TIMEOUT_NEOPIXEL = 300.0  # Required — long retry window.
HEALTH_TIMEOUT_CAMERA = 300.0  # Required — covers swapping batteries / USB.
HEALTH_TIMEOUT_PRINTER = 300.0  # Required (receipt) — long retry window.
HEALTH_TIMEOUT_NET_LOCAL = 5.0  # Optional — quick check, no blocking.
HEALTH_TIMEOUT_NET_WWW = 5.0  # Optional — quick check, no blocking.
HEALTH_RECHECK_INTERVAL = 10.0  # Background re-probe cadence for unavailable.

# --- Print compositor templates (folders under TEMPLATE_BASE_DIR) ---
# BOOTH_ACTIVE_TEMPLATE: unset/empty = plain single-shot
#                        folder with shot_count=1 = single shot + final overlay
#                        folder with shot_count>1 = series / strip mode
TEMPLATE_BASE_DIR = os.environ.get(
    "BOOTH_TEMPLATE_BASE_DIR", "/opt/photobooth/templates"
)
ACTIVE_TEMPLATE = os.environ.get("BOOTH_ACTIVE_TEMPLATE", "strip_test_template") or None

# --- Button roles (GPIO event labels — context-dependent) ---
# KEEP_BUTTON  GPIO 23 green: keep (review) | print receipt (idle) | show last shot (series_capture)
# REDO_BUTTON  GPIO 24 red:   redo (review) | start over (series_capture)
# "capture"    GPIO 25 blue:  start capture (idle) | continue / next shot (review)
KEEP_BUTTON = "green"  # GPIO 23 / pin 16
REDO_BUTTON = "red"  # GPIO 24 / pin 18

# --- Post-capture reaction phrases (one is chosen at random) ---
CAPTURE_PHRASES = [
    "Awesome!  ",
    "Looking great!  ",
    "Love it!  ",
    "Stunning!  ",
    "Perfect shot!  ",
    "Beautiful!  ",
    "Amazing!  ",
    "That's the one!  ",
]

# --- Django screen URLs ---
ATTRACT_URL = "http://127.0.0.1:8000/main/attract/"
REVIEW_URL = "http://127.0.0.1:8000/main/last_capture/"
SINGLE_FINAL_URL = "http://127.0.0.1:8000/main/single_final/"
SERIES_FINAL_URL = "http://127.0.0.1:8000/main/series_final/"
SERIES_CAPTURE_URL = "http://127.0.0.1:8000/main/series_capture/"
UNAVAILABLE_URL = "http://127.0.0.1:8000/main/unavailable/"

# --- Phase 5: unavailable-mode + resume ---
RESUME_STATE_PATH = os.environ.get("BOOTH_RESUME_STATE_PATH", "/var/lib/photobooth/resume.json")
CAMERA_UNAVAILABLE_TEXT = "Camera not detected. Check power and USB.  "
PRINTER_UNAVAILABLE_TEXT = "Printer not responding  "
UNAVAILABLE_SCROLL_COLOR = (255, 0, 0)  # RED — inlined to avoid importing neopixel.RED


class PhotoBooth:
    async def run(self):
        loop = asyncio.get_running_loop()
        self.rpi = RPi()
        self._print_counts: dict = {}
        self._last_uploaded_path: str = ""
        self._last_uploaded_key: str = ""
        if Uploader is not None:
            try:
                self.uploader = Uploader(bucket_name=S3_BUCKET)
                logger.info("Uploader ready: bucket=%s", S3_BUCKET)
            except Exception as exc:
                logger.warning(
                    "Uploader unavailable: %s (uploads/prints disabled)", exc
                )
                self.uploader = None
        else:
            logger.warning(
                "Uploader not available (boto3/utilities missing) — "
                "uploads/prints disabled"
            )
            self.uploader = None

        await self._startup()

        # Phase 5: list of paths from a resume record on disk. When non-empty
        # on the next ``capture`` event, the booth re-enters ``_run_series``
        # with these shots already captured rather than starting fresh.
        self._pending_resume_shots: list = []

        self.strip = None
        if ACTIVE_TEMPLATE:
            try:
                loader = LocalTemplateLoader(TEMPLATE_BASE_DIR)
                self.strip = PhotoStrip(loader=loader, template_name=ACTIVE_TEMPLATE)
                mode = "series" if self.strip.shot_count > 1 else "single+overlay"
                logger.info(
                    "Template loaded: name=%s shots=%d mode=%s",
                    ACTIVE_TEMPLATE,
                    self.strip.shot_count,
                    mode,
                )
            except Exception as exc:
                logger.warning(
                    "Template load failed: %s — falling back to plain single-shot",
                    exc,
                )
        else:
            logger.info("No active template — plain single-shot mode")

        # Phase 5: if a previous session left a resume record on disk,
        # navigate to the appropriate screen before opening the event loop.
        # ``_resume_from`` sets ``_pending_resume_shots`` for series mode;
        # the next blue-button event picks it up.
        resume_state = state_store.load_json(RESUME_STATE_PATH)
        if resume_state:
            await self._resume_from(resume_state)

        self.rpi.setup_gpio_events(loop)

        if not self._pending_resume_shots:
            await self.rpi.display_url(ATTRACT_URL)
            attract_text = "Press the big blue button to begin!  "
        else:
            attract_text = "Press the big blue button to continue!  "
        attract = asyncio.create_task(
            self.panel.scroll(text=attract_text, speed=0.005, count=999)
        )
        last_print_time: float = 0.0

        while True:
            event = await self.rpi.next_event()
            # Forensic trail for the spurious-capture investigation: every
            # event dispatched by the main loop is recorded here, regardless
            # of which branch handles it below. Pair with the "Button event:"
            # line emitted in rpi._on_press to correlate GPIO arrival vs
            # main-loop processing latency.
            logger.debug("Main loop event: %s", event)

            if event == "capture":
                is_series = self.strip is not None and self.strip.shot_count > 1
                mode = "series" if is_series else "single"
                logger.info("Capture started: mode=%s", mode)
                attract.cancel()

                # Phase 5: a cross-process resume staged ``_pending_resume_shots``
                # in ``run()``. Consume it here so the series re-enters at the
                # right shot; clear before the call so a second capture starts
                # fresh even if this one fails.
                resume_shots = self._pending_resume_shots
                self._pending_resume_shots = []
                if is_series:
                    image_path = await self._run_series(
                        starting_shots=resume_shots if resume_shots else None
                    )
                else:
                    image_path = await self._run_single()

                if image_path is None:
                    logger.info("Capture cancelled by user")
                    self._clear_resume_state()
                    await self._flush_events()
                    await self.rpi.display_url(ATTRACT_URL)
                    logger.debug("Returning to attract mode")
                    attract = asyncio.create_task(
                        self.panel.scroll(
                            text="Press the big blue button to begin!  ",
                            speed=0.005,
                            count=999,
                        )
                    )
                    continue

                self.rpi.copy_to_last_shot(image_path)
                self.camera.copy_last_shot_to_dir(dir=BOOTH_DIR)
                final_url = SERIES_FINAL_URL if is_series else SINGLE_FINAL_URL
                logger.info("Capture completed: mode=%s file=%s", mode, image_path)

                # Navigate immediately — upload runs in background while user views final screen
                await self.rpi.display_url(final_url)
                upload_task = None
                if self.uploader is not None:
                    # Generate key up-front so the reprint path can reuse the same one.
                    key = self.uploader.make_key(image_path)
                    logger.info("Uploading: file=%s bucket=%s", image_path, S3_BUCKET)
                    upload_task = asyncio.create_task(
                        self.uploader.upload(image_path, key=key)
                    )
                    self._last_uploaded_path = image_path
                    self._last_uploaded_key = key

                # Hold final screen up to 60 s; green = print receipt, anything else = attract
                await self._flush_events()
                try:
                    decision = await asyncio.wait_for(self.rpi.next_event(), timeout=60)
                except asyncio.TimeoutError:
                    logger.debug("Final-screen timeout — returning to attract")
                    decision = None

                if decision in (KEEP_BUTTON, "capture") and upload_task is not None:
                    try:
                        upload_url = await upload_task
                    except Exception as exc:
                        logger.error("Upload failed: %s", exc)
                        upload_url = None
                        self._last_uploaded_key = ""  # nothing on S3 to reprint
                    if upload_url is not None:
                        logger.info("Printing receipt for %s", image_path)
                        await self._print_with_recovery(upload_url)
                        self._print_counts[image_path] = 1
                        last_print_time = loop.time()
                elif upload_task is not None:
                    try:
                        await upload_task
                    except Exception as exc:
                        logger.error("Upload failed: %s", exc)
                        self._last_uploaded_key = ""

                # Clean session completion — drop any resume record before
                # returning to attract.
                self._clear_resume_state()
                await self._flush_events()
                await self.rpi.display_url(ATTRACT_URL)
                logger.debug("Returning to attract mode")
                attract = asyncio.create_task(
                    self.panel.scroll(
                        text="Press the big blue button to begin!  ",
                        speed=0.005,
                        count=999,
                    )
                )

            elif event == KEEP_BUTTON:
                if self.uploader is None:
                    continue

                now = loop.time()
                if now - last_print_time <= 3:
                    continue

                # Reprint targets the most recently uploaded object (by its S3 key,
                # not by re-generating one from the file path — make_key() is
                # non-deterministic, so re-deriving would point at a nonexistent object).
                last_shot = self._last_uploaded_path
                last_key = self._last_uploaded_key
                if not last_shot or not last_key:
                    logger.info("Print button pressed but no shot exists yet")
                    continue

                count = self._print_counts.get(last_shot, 0)
                if count >= MAX_PRINTS:
                    logger.info(
                        "Print rate limit: %d/%d for %s",
                        count,
                        MAX_PRINTS,
                        last_shot,
                    )
                    attract.cancel()
                    await self._flush_events()
                    await self.panel.scroll(
                        text="Max prints reached, sorry!  ", count=1
                    )
                    await self.rpi.display_url(ATTRACT_URL)
                    attract = asyncio.create_task(
                        self.panel.scroll(
                            text="Press the big blue button to begin!  ",
                            speed=0.005,
                            count=999,
                        )
                    )
                    continue

                logger.info("Reprinting receipt for %s", last_shot)
                attract.cancel()
                url = self.uploader.public_url(last_key)
                await self.panel.scroll(text="Printing...  ", speed=0.005, count=1)
                await self._print_with_recovery(url)
                self._print_counts[last_shot] = count + 1
                # Set the rate-limit anchor AFTER the print finishes; otherwise
                # presses queued during the (5+ second) print pop afterwards and
                # already exceed the 3 s cooldown measured from print start.
                last_print_time = loop.time()
                await self._flush_events()
                attract = asyncio.create_task(
                    self.panel.scroll(
                        text="Press the big blue button to begin!  ",
                        speed=0.005,
                        count=999,
                    )
                )

            elif event == REDO_BUTTON:
                attract.cancel()
                await self._flush_events()
                await self.rpi.display_url(ATTRACT_URL)
                attract = asyncio.create_task(
                    self.panel.scroll(
                        text="Press the big blue button to begin!  ",
                        speed=0.005,
                        count=999,
                    )
                )

    async def _flush_events(self) -> None:
        """Drain any stale button events left over from the previous action.

        The brief sleep yields to the event loop so any in-flight
        call_soon_threadsafe callbacks are processed before we drain.
        """
        await asyncio.sleep(0.1)
        while not self.rpi.event_queue.empty():
            try:
                self.rpi.event_queue.get_nowait()
            except Exception:
                break

    # ------------------------------------------------------------------
    # Phase 5: unavailable-mode + resume
    # ------------------------------------------------------------------

    def _save_resume_state(self, state: dict) -> None:
        """Persist a resume record to RESUME_STATE_PATH (atomic JSON write).

        Called immediately before any hardware op that can fail at runtime
        so a crash mid-failure (or a recovery from a cold restart) finds
        the most recent step on disk. Errors writing state are logged but
        do not abort the capture flow — the booth keeps running on stale
        resume info rather than losing the current shot.
        """
        try:
            state_store.save_json_atomic(RESUME_STATE_PATH, state)
        except Exception as exc:
            logger.warning("Resume state write failed: %s", exc)

    def _clear_resume_state(self) -> None:
        """Remove the resume file. Called on clean session completion."""
        try:
            state_store.delete_if_exists(RESUME_STATE_PATH)
        except Exception as exc:
            logger.warning("Resume state delete failed: %s", exc)

    def _classify_error(self, exc: BaseException, hint: Optional[str] = None) -> tuple:
        """Map an exception to (component_name, neopixel scroll text).

        ``hint`` lets the caller pin the component (camera vs printer) when
        the exception type alone is ambiguous (e.g. ``RuntimeError`` is
        raised by both ``gphoto2`` and ``escpos`` paths).
        """
        if hint == "printer":
            return ("printer", PRINTER_UNAVAILABLE_TEXT)
        # Default: camera. Phase 5 only wires camera + printer; internet
        # failures are Phase 6's responsibility (offline queue).
        return ("camera", CAMERA_UNAVAILABLE_TEXT)

    async def display_url_with_context(self, url: str, **params) -> None:
        """Navigate to ``url`` with optional query-string params.

        Phase 5 uses this only for the post-recovery navigation back to
        the series_capture page. Phase 7 will route every navigation
        through this helper so the in-frame series banner (``?shot=X&
        total=N&mode=series``) populates from a single source.
        """
        if params:
            url = f"{url}?{urlencode(params)}"
        await self.rpi.display_url(url)

    async def _enter_unavailable(self, component: str, scroll_text: str) -> None:
        """Switch the booth to unavailable mode and await component recovery.

        Caller has already saved any resume state it cares about (via
        ``_save_resume_state``) before invoking the failing operation.
        This method handles the display + scroll + wait + cleanup, then
        returns once ``HealthMonitor`` reports ``component`` is ready.

        The kiosk is parked on UNAVAILABLE_URL and the neopixel scrolls
        ``scroll_text`` in red continuously (``count=999``). Button events
        accumulated during the outage are drained before returning so a
        long press during the dead window doesn't fire on recovery.
        """
        logger.warning("Entering unavailable mode: component=%s", component)
        await self.rpi.display_url(UNAVAILABLE_URL)
        scroll_task = asyncio.create_task(
            self.panel.scroll(
                text=scroll_text,
                speed=0.005,
                count=999,
                color=UNAVAILABLE_SCROLL_COLOR,
            )
        )
        try:
            await self.health.wait_until_ready(component, timeout=None)
        finally:
            scroll_task.cancel()
            try:
                await scroll_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("Unavailable scroll exit error: %s", exc)
            self.panel.clear()
        await self._flush_events()
        logger.info("Exiting unavailable mode: component=%s ready", component)

    async def _resume_from(self, state: dict) -> None:
        """Re-enter the booth at the saved step after a cold restart.

        Phase 5 supports cross-process resume for series mode only —
        single-shot has no partial state worth preserving. For a series
        with captured shots in flight, this navigates to the between-
        shots page with the right ``?shot=X&total=N&mode=series`` query
        params so the user sees where they left off; the next blue-button
        event re-enters ``_run_series`` with the restored shots list.

        ``self._pending_resume_shots`` is read by the main loop's
        ``capture`` handler to bypass starting a fresh series.
        """
        mode = state.get("mode")
        shots = state.get("series_shots") or []
        total = state.get("total") or 0
        if mode != "series" or not shots:
            logger.info("Resume state present but not actionable; clearing")
            self._clear_resume_state()
            return
        logger.info(
            "Resuming series: shots_captured=%d total=%d",
            len(shots),
            total,
        )
        self._pending_resume_shots = list(shots)
        await self.display_url_with_context(
            SERIES_CAPTURE_URL,
            mode="series",
            shot=len(shots) + 1,
            total=total,
        )

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def _startup(self):
        """Bring the booth online with dependency-aware health probes.

        Phase 4: each component is registered with ``HealthMonitor`` and
        we ``wait_until_ready`` instead of raising on the first failure.
        Required components (web, neopixel, camera, receipt printer) use
        a long timeout; optional components (local LAN, internet) use a
        short timeout and log+continue if not present.

        After init completes, ``recheck_loop`` runs in the background so
        a component that fails at runtime and later self-heals flips
        back to ``ready`` without intervention (consumed in later phases).
        """
        self.health = HealthMonitor()
        _load_probes()

        logger.info("Starting Django web server")
        await self.rpi.start_web()
        self.health.register("web", probe_web_available)
        if not await self.health.wait_until_ready("web", timeout=HEALTH_TIMEOUT_WEB):
            raise RuntimeError("Django web server did not respond within timeout")
        logger.debug("Django web server responding")

        logger.info("Starting kiosk browser")
        await self.rpi.start_kiosk()
        self.rpi.reset_last_shot()

        logger.debug("Initializing components")

        self.health.register("neopixel", probe_neopixel_available)
        if not await self.health.wait_until_ready("neopixel", timeout=HEALTH_TIMEOUT_NEOPIXEL):
            raise RuntimeError("Neopixel panel did not come online within timeout")
        self.panel = await self._init_with_retry(
            "neopixel",
            lambda: self.rpi.add_neopixel(name="main", control=board.D18),
        )
        logger.info("Component online: neopixel name=main (8x32)")

        self.health.register("camera", lambda: probe_camera_available(CAMERA_MODEL))
        if not await self.health.wait_until_ready("camera", timeout=HEALTH_TIMEOUT_CAMERA):
            raise RuntimeError("Camera did not come online within timeout")
        self.camera = await self._init_with_retry(
            "camera",
            lambda: self.rpi.add_camera(
                name="main",
                model=CAMERA_MODEL,
                startup_config=CAMERA_STARTUP_CONFIG,
            ),
        )
        logger.info("Component online: camera name=main model=%s", CAMERA_MODEL)

        self.health.register("printer", probe_printer_available)
        if not await self.health.wait_until_ready("printer", timeout=HEALTH_TIMEOUT_PRINTER):
            raise RuntimeError("Receipt printer did not come online within timeout")
        self.printer = await self._init_with_retry(
            "printer",
            lambda: self.rpi.add_printer(name="receipt", model="PBM-8350U"),
        )
        logger.info("Component online: printer name=receipt model=PBM-8350U")

        panel_test = asyncio.create_task(self.panel.panel_test())

        self.health.register("net_local", probe_local_network)
        self.health.register("net_www", probe_internet_available)
        local_ok = await self.health.wait_until_ready("net_local", timeout=HEALTH_TIMEOUT_NET_LOCAL)
        www_ok = await self.health.wait_until_ready("net_www", timeout=HEALTH_TIMEOUT_NET_WWW)
        logger.info("Network check: local=%s www=%s", local_ok, www_ok)
        if local_ok:
            self.rpi.toggle_led(label="net_local", on=True)
        if www_ok:
            self.rpi.toggle_led(label="net_www", on=True)

        self.rpi.toggle_led(label="camera_rdy", on=True)
        self.rpi.toggle_led(label="print_rdy", on=True)

        await panel_test
        self.rpi.toggle_led(label="shutter_rdy", on=True)

        self._recheck_task = asyncio.create_task(
            self.health.recheck_loop(interval=HEALTH_RECHECK_INTERVAL)
        )
        logger.info("Booth is online and ready")

    async def _init_with_retry(self, name: str, factory):
        """Run a hardware ``factory`` after its probe reports ready.

        If init still raises (rare — a transient state between probe
        passing and instantiation), re-await ``wait_until_ready(name)``
        with no timeout and try again. Keeps the booth from crashing on
        the boundary case where USB enumeration completes between the
        probe and the open.
        """
        attempts = 0
        while True:
            attempts += 1
            try:
                return factory()
            except Exception as exc:
                logger.warning(
                    "Component init failed: %s (attempt %d) — %s",
                    name,
                    attempts,
                    exc,
                )
                await self.health.wait_until_ready(name, timeout=None)

    # ------------------------------------------------------------------
    # Capture flows
    # ------------------------------------------------------------------

    async def _run_single(self) -> Optional[str]:
        """Single-shot flow. Returns final image path, or None on redo / failure."""
        logger.debug("Starting single flow")
        image_path = await self._take_one_shot(
            resume_context={
                "mode": "single",
                "pending_step": "capture",
                "template_name": ACTIVE_TEMPLATE,
            }
        )
        if image_path is None:
            # Camera failed; user is back from unavailable mode.
            return None
        decision = await self._review_shot(image_path, series_mode=False)
        if decision == "redo":
            logger.info("Single capture redo by user")
            return None

        if self.strip is not None and self.strip.shot_count == 1:
            loop = asyncio.get_running_loop()
            final_path = (
                f"{BOOTH_DIR}/final_{datetime.now().strftime('%Y%m%d-%Hh%Mm%Ss')}.jpg"
            )
            image_path = await loop.run_in_executor(
                None, self.strip.compose, [image_path], final_path
            )
            logger.info("Strip composed: file=%s shots=1", final_path)
        return image_path

    async def _run_series(self, starting_shots: Optional[list] = None) -> Optional[str]:
        """Series flow. Returns composited strip path, or None if cancelled.

        Phase 5: ``starting_shots`` allows a cross-process or in-process
        resume to re-enter the loop with already-captured paths preserved.
        On a camera failure mid-series, ``_take_one_shot`` returns ``None``
        after the user recovers; we navigate to the between-shots page so
        they can press blue to continue with the same shot, or red to
        cancel the series.
        """
        logger.debug("Starting series flow")
        loop = asyncio.get_running_loop()
        total = self.strip.shot_count
        shots = list(starting_shots) if starting_shots else []

        while len(shots) < total:
            if shots:
                await self.panel.scroll(
                    text=f"Shot {len(shots) + 1} of {total}! Get ready!  ",
                    speed=0.005,
                    count=1,
                )
            image_path = await self._take_one_shot(
                resume_context={
                    "mode": "series",
                    "pending_step": "capture",
                    "series_shots": list(shots),
                    "shot_index": len(shots) + 1,
                    "total": total,
                    "template_name": ACTIVE_TEMPLATE,
                }
            )
            if image_path is None:
                # Camera failed; user has just come back from unavailable.
                # Hand control to the between-shots page so they can press
                # blue to retry the failed shot, or red to cancel.
                if not shots:
                    logger.info("Series cancelled: camera failure before shot 1")
                    return None
                series_decision = await self._series_capture_review(shots, last_decided=None)
                if series_decision == "start_over":
                    logger.info("Series cancelled by user (start over)")
                    return None
                continue
            decision = await self._review_shot(image_path, series_mode=True)

            if decision == "redo":
                series_decision = await self._series_capture_review(
                    shots, last_decided=image_path
                )
                if series_decision == "start_over":
                    logger.info("Series cancelled by user (start over)")
                    return None
                continue  # retake current slot (or advance, if shots was mutated)

            shots.append(image_path)

            if len(shots) >= total:
                continue

            # decision == "keep" — go to between-shots review page
            series_decision = await self._series_capture_review(
                shots, last_decided=image_path
            )
            if series_decision == "start_over":
                logger.info("Series cancelled by user (start over)")
                return None

        strip_path = (
            f"{BOOTH_DIR}/strip_{datetime.now().strftime('%Y%m%d-%Hh%Mm%Ss')}.jpg"
        )
        result = await loop.run_in_executor(None, self.strip.compose, shots, strip_path)
        logger.info("Strip composed: file=%s shots=%d", strip_path, total)
        return result

    # ------------------------------------------------------------------
    # Review helpers
    # ------------------------------------------------------------------

    async def _take_one_shot(self, resume_context: Optional[dict] = None) -> Optional[str]:
        """Run the countdown and capture one image.

        Timing target (v0.5.0 Phase 1): button-press → shutter ≈ 2.0s.
        3/2/1 each scroll for 0.4s (1.2s total). Capture is then dispatched
        and ``Smile! :D`` scrolls in parallel for 0.8s. If the camera's real
        gphoto2 latency extends past the Smile! scroll, twinkle runs as a
        visual fallback until the capture task resolves.

        Phase 2: the post-capture reaction phrase is launched as a
        background task on ``self._phrase_task`` so the caller can navigate
        to the review screen in parallel. ``_review_shot`` cancels/awaits
        the task before returning, guaranteeing the panel is idle by the
        next state transition.

        Phase 5: ``resume_context`` (a dict describing the current capture
        position) is persisted to ``RESUME_STATE_PATH`` before the camera
        is invoked. On a runtime camera failure, the booth enters
        unavailable mode and waits for recovery, then returns ``None`` so
        the caller can route the user back to the appropriate screen.
        """
        if resume_context is not None:
            self._save_resume_state(resume_context)
        await self.panel.scroll_for_duration(text="3...", duration_s=0.4)
        await self.panel.scroll_for_duration(text="2...", duration_s=0.4)
        await self.panel.scroll_for_duration(text="1...", duration_s=0.4)
        capture_task = asyncio.create_task(self.camera.capture_async())
        await self.panel.scroll_for_duration(text="Smile! :D", duration_s=0.8)
        twinkle_task = None
        if not capture_task.done():
            twinkle_task = asyncio.create_task(self.panel.twinkle(count=30))
        try:
            image_path = await capture_task
        except Exception as exc:
            if twinkle_task is not None:
                twinkle_task.cancel()
            self.panel.clear()
            logger.error("Camera capture failed: %s", exc)
            component, scroll_text = self._classify_error(exc, hint="camera")
            await self._enter_unavailable(component, scroll_text)
            return None
        if twinkle_task is not None:
            twinkle_task.cancel()
        self.panel.clear()
        logger.info("Shot captured: file=%s", image_path)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._compress_image, image_path)
        try:
            size = os.path.getsize(image_path)
            logger.debug("Compressed shot: file=%s size=%d bytes", image_path, size)
        except OSError:
            pass
        self._phrase_task = asyncio.create_task(
            self.panel.scroll(
                text=random.choice(CAPTURE_PHRASES), speed=0.001, count=1
            )
        )
        return image_path

    @staticmethod
    def _compress_image(
        image_path: str, max_dimension: int = 2048, quality: int = 85
    ) -> None:
        """Resize to max_dimension on the longest side and recompress in-place."""
        from PIL import Image

        with Image.open(image_path) as img:
            if max(img.size) > max_dimension:
                img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
            img.save(image_path, "JPEG", quality=quality, optimize=True)

    async def _review_shot(self, image_path: str, series_mode: bool = False) -> str:
        """Display shot in the review frame and wait for a decision.

        Returns:
            "keep"     — accept this shot
            "redo"     — cancel (single: → attract; series: → attract/cancel)
            "continue" — accept and skip series_capture (series_mode only)

        Phase 2: navigates to the review URL without awaiting the post-
        capture reaction phrase. Any phrase task launched by
        ``_take_one_shot`` is cancelled/awaited at the end so the panel
        is idle by the next state transition.
        """
        self.rpi.copy_to_last_shot(image_path)
        await self.rpi.display_url(REVIEW_URL)
        await self._flush_events()

        decision = await self.rpi.next_event()
        while decision not in (KEEP_BUTTON, REDO_BUTTON, "capture"):
            decision = await self.rpi.next_event()

        # Phase 2: clean up the background reaction phrase before yielding
        # control back to the caller. Use getattr so tests that drive
        # _review_shot directly (without going through _take_one_shot)
        # keep working.
        phrase_task = getattr(self, "_phrase_task", None)
        if phrase_task is not None:
            if not phrase_task.done():
                phrase_task.cancel()
            try:
                await phrase_task
            except asyncio.CancelledError:
                pass
            self._phrase_task = None

        result = "redo" if decision == REDO_BUTTON else "keep"
        logger.debug("Shot review decision: %s (button=%s)", result, decision)
        return result

    async def _series_capture_review(self, shots: list, last_decided: str) -> str:
        """Between-shots review page.

        Returns "continue" (user pressed CAPTURE to take next shot) or
        "start_over" (user pressed REDO_BUTTON to cancel the series).

        ``last_decided`` is the path of the shot whose decision (keep or redo)
        brought the user to this page. When the user presses KEEP_BUTTON
        ("show last shot"), that shot is re-reviewed; the re-review's outcome
        may mutate ``shots`` in place:

        - Re-review returns "keep" on a shot NOT in ``shots`` (i.e. the
          original decision was redo): the shot is appended — the user
          changed their mind and is keeping it after all.
        - Re-review returns "redo" on a shot IN ``shots`` (i.e. the
          original decision was keep): the shot is removed — the user
          changed their mind and is redoing it after all.
        - Re-affirming the original decision is a no-op.

        After any re-review, the page is re-displayed and we wait for the
        next BLUE/GREEN/RED. This provides a buffer between a decision
        change and the countdown for the next shot.
        """
        while True:
            await self.rpi.display_url(SERIES_CAPTURE_URL)
            await self._flush_events()
            scroll = asyncio.create_task(
                self.panel.scroll(
                    text="Press the big blue button to continue!  ",
                    speed=0.005,
                    count=999,
                )
            )
            try:
                while True:
                    event = await self.rpi.next_event()
                    if event == "capture":
                        return "continue"
                    if event == REDO_BUTTON:
                        return "start_over"
                    if event == KEEP_BUTTON:
                        if not last_decided:
                            continue
                        scroll.cancel()
                        self.panel.clear()
                        decision = await self._review_shot(
                            last_decided, series_mode=False
                        )
                        if decision == "keep" and last_decided not in shots:
                            logger.info(
                                "Series undo redo: keeping %s", last_decided
                            )
                            shots.append(last_decided)
                        elif decision == "redo" and last_decided in shots:
                            logger.info(
                                "Series undo keep: redoing %s", last_decided
                            )
                            shots.remove(last_decided)
                        break  # re-show series_capture page + reset scroll
            finally:
                scroll.cancel()

    # ------------------------------------------------------------------
    # Receipt printer
    # ------------------------------------------------------------------

    async def _print_with_recovery(self, url: str) -> None:
        """Run ``_do_print`` in the thread executor; on failure, enter
        unavailable mode and retry once after the printer recovers.

        ``url`` is a presigned S3 URL (or public URL on reprint) — kept in
        memory only and never persisted to ``resume.json``, since presigned
        URLs are sensitive credential material.
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._do_print, url)
            return
        except Exception as exc:
            logger.error("Receipt print failed: %s", exc)
            component, scroll_text = self._classify_error(exc, hint="printer")
            await self._enter_unavailable(component, scroll_text)
        try:
            await loop.run_in_executor(None, self._do_print, url)
        except Exception as exc:
            logger.error("Receipt print retry failed: %s", exc)

    def _do_print(self, url: str) -> None:
        """Synchronous receipt printer — runs in thread executor from async caller.

        The url is a presigned S3 URL that becomes a QR code; never log it —
        the embedded AWS signature is sensitive credential material.
        """
        logger.debug("Receipt printing started")
        try:
            self.printer.text("Capturing Time Photography")
            self.printer.ln()
            self.printer.ln()
            self.printer.text("Thank you for using our photobooth!")
            self.printer.ln()
            self.printer.ln()
            self.printer.text("Please visit us at http://capturingtimephoto.net")
            self.printer.ln()
            self.printer.text("    to schedule your free 30 minute consultation")
            self.printer.ln()
            self.printer.text("    for your next portrait session or event!")
            self.printer.ln()
            self.printer.ln()
            self.printer.text("Mention this photobooth when you book your next")
            self.printer.ln()
            self.printer.text("session with us & receive an extra 10% discount!")
            self.printer.ln()
            self.printer.ln()
            self.printer.text("Scan the QR code below to download your photo:")
            self.printer.ln()
            self.printer.qr(content=url, size=5)
            self.printer.ln()
            self.printer.text("Reach us at contact@capturingtimephoto.net")
            self.printer.ln()
            self.printer.text("Tag us on")
            self.printer.ln()
            self.printer.text("Instagram: @capturingtimephoto")
            self.printer.ln()
            self.printer.text("Facebook: @capturingtimephotollc")
            self.printer.cut()
            logger.debug("Receipt print complete")
        except Exception as exc:
            logger.error("Receipt print failed: %s", exc)
            raise


def main() -> None:
    setup_logging()
    logger.info("Photobooth runtime starting")
    try:
        asyncio.run(PhotoBooth().run())
    finally:
        logger.info("Photobooth runtime exiting")


if __name__ == "__main__":
    main()
