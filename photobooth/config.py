"""Runtime configuration constants for the photobooth.

Per-booth behavior is read from environment variables (typically loaded by
systemd via ``EnvironmentFile=-/etc/ctp/booth.env``). Each key falls back to
the hardcoded default here, so an empty/missing env file is safe. These
constants are the entire surface for per-booth configuration — see
``tests/test_env_example_consistency.py`` for the key-name drift guard.
"""

import os

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
TEMPLATE_BASE_DIR = os.environ.get("BOOTH_TEMPLATE_BASE_DIR", "/opt/photobooth/templates")
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

# Looping invite scroll shown on the LED panel while at the attract screen.
ATTRACT_SCROLL_TEXT = "Press the big blue button to begin!  "

# --- Phase 5: unavailable-mode + resume ---
RESUME_STATE_PATH = os.environ.get("BOOTH_RESUME_STATE_PATH", "/var/lib/photobooth/resume.json")
CAMERA_UNAVAILABLE_TEXT = "Camera not detected. Check power and USB.  "
PRINTER_UNAVAILABLE_TEXT = "Printer not responding  "
UNAVAILABLE_SCROLL_COLOR = (255, 0, 0)  # RED — inlined to avoid importing neopixel.RED
# Minimum time to hold the unavailable screen even after the probe says
# ready, so a fast recovery (e.g. USB re-enumeration completes within 1s
# of the failed capture) doesn't flash by before the user can register it.
UNAVAILABLE_MIN_HOLD_SECONDS = 2.5

# --- Phase 6: offline upload queue ---
UPLOAD_QUEUE_PATH = os.environ.get(
    "BOOTH_UPLOAD_QUEUE_PATH", "/var/lib/photobooth/upload_queue.json"
)
UPLOAD_TIMEOUT_SECONDS = 5.0
UPLOADING_SCROLL_TEXT = "Uploading...  "
PENDING_UPLOAD_NOTICE = (
    "* Photo upload pending - your QR will work \n" "once the booth reconnects to the internet."
)
# Worker backoff: start fast (5s) so a transient flap drains promptly;
# double after each failure; cap at 5 min so a long outage doesn't
# eat the CPU.
UPLOAD_WORKER_BACKOFF_INITIAL = 5.0
UPLOAD_WORKER_BACKOFF_CAP = 300.0
