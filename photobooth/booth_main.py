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

import board

from photobooth import RPi, Uploader
from photobooth.logging_config import setup_logging
from photobooth.strip import PhotoStrip
from photobooth.template_loader import LocalTemplateLoader

logger = logging.getLogger(__name__)

# --- Hardware / storage ---
S3_BUCKET = os.environ.get("BOOTH_S3_BUCKET", "public.capturingtimephoto.net")
BOOTH_DIR = os.environ.get("BOOTH_IMAGE_DIR", "/opt/booth_images")
CAMERA_MODEL = os.environ.get("BOOTH_CAMERA_MODEL", "Canon EOS 800D")
CAMERA_STARTUP_CONFIG = {
    "autoexposuremode": 3,  # Manual — prevents built-in flash from auto-firing
}
MAX_PRINTS = int(os.environ.get("BOOTH_MAX_PRINTS", "3"))

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

        self.rpi.setup_gpio_events(loop)

        await self.rpi.display_url(ATTRACT_URL)
        attract = asyncio.create_task(
            self.panel.scroll(
                text="Press the big blue button to begin!  ", speed=0.005, count=999
            )
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

                image_path = (
                    await self._run_series() if is_series else await self._run_single()
                )

                if image_path is None:
                    logger.info("Capture cancelled by user")
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
                        await loop.run_in_executor(None, self._do_print, upload_url)
                        self._print_counts[image_path] = 1
                        last_print_time = loop.time()
                elif upload_task is not None:
                    try:
                        await upload_task
                    except Exception as exc:
                        logger.error("Upload failed: %s", exc)
                        self._last_uploaded_key = ""

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
                await loop.run_in_executor(None, self._do_print, url)
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
    # Startup
    # ------------------------------------------------------------------

    async def _startup(self):
        logger.info("Starting Django web server")
        await self.rpi.start_web()
        while not self.rpi.check_web():
            await asyncio.sleep(0.1)
        logger.debug("Django web server responding")

        logger.info("Starting kiosk browser")
        await self.rpi.start_kiosk()
        self.rpi.reset_last_shot()

        logger.debug("Initializing components")
        try:
            self.panel = self.rpi.add_neopixel(name="main", control=board.D18)
            logger.info("Component online: neopixel name=main (8x32)")
        except Exception as exc:
            logger.error("Component offline: neopixel name=main — %s", exc)
            raise
        try:
            self.camera = self.rpi.add_camera(
                name="main", model=CAMERA_MODEL, startup_config=CAMERA_STARTUP_CONFIG
            )
            logger.info("Component online: camera name=main model=%s", CAMERA_MODEL)
        except Exception as exc:
            logger.error(
                "Component offline: camera name=main model=%s — %s", CAMERA_MODEL, exc
            )
            raise
        try:
            self.printer = self.rpi.add_printer(name="receipt", model="PBM-8350U")
            logger.info("Component online: printer name=receipt model=PBM-8350U")
        except Exception as exc:
            logger.error("Component offline: printer name=receipt — %s", exc)
            raise

        panel_test = asyncio.create_task(self.panel.panel_test())

        local_ok = bool(self.rpi.net_check_local())
        www_ok = bool(self.rpi.net_check_www())
        logger.info("Network check: local=%s www=%s", local_ok, www_ok)
        if local_ok:
            self.rpi.toggle_led(label="net_local", on=True)
        if www_ok:
            self.rpi.toggle_led(label="net_www", on=True)

        self.rpi.toggle_led(label="camera_rdy", on=True)
        self.rpi.toggle_led(label="print_rdy", on=True)

        await panel_test
        self.rpi.toggle_led(label="shutter_rdy", on=True)
        logger.info("Booth is online and ready")

    # ------------------------------------------------------------------
    # Capture flows
    # ------------------------------------------------------------------

    async def _run_single(self) -> Optional[str]:
        """Single-shot flow. Returns final image path, or None on redo."""
        logger.debug("Starting single flow")
        image_path = await self._take_one_shot()
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

    async def _run_series(self) -> Optional[str]:
        """Series flow. Returns composited strip path, or None if cancelled."""
        logger.debug("Starting series flow")
        loop = asyncio.get_running_loop()
        total = self.strip.shot_count
        shots = []

        while len(shots) < total:
            if shots:
                await self.panel.scroll(
                    text=f"Shot {len(shots) + 1} of {total}! Get ready!  ",
                    speed=0.005,
                    count=1,
                )
            image_path = await self._take_one_shot()
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

    async def _take_one_shot(self) -> str:
        """Run the countdown and capture one image."""
        for label in ("3...", "2...", "1...", "Smile! :D"):
            await self.panel.scroll(text=label, speed=0.001)
        twinkle_task = asyncio.create_task(self.panel.twinkle(count=30))
        image_path = await self.camera.capture_async()
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
        await self.panel.scroll(
            text=random.choice(CAPTURE_PHRASES), speed=0.001, count=1
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
        """
        self.rpi.copy_to_last_shot(image_path)
        await self.rpi.display_url(REVIEW_URL)
        await self._flush_events()

        decision = await self.rpi.next_event()
        while decision not in (KEEP_BUTTON, REDO_BUTTON, "capture"):
            decision = await self.rpi.next_event()

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
