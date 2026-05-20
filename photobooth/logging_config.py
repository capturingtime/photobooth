"""Logging setup for the photobooth runtime.

Two handlers on the ``photobooth.*`` logger tree:

* ``RotatingFileHandler`` → ``/var/log/photobooth.log`` at DEBUG (5×10MB backups)
* ``StreamHandler(stderr)`` at WARNING (systemd captures stderr → journald)

The root level is gated by the ``BOOTH_LOG_LEVEL`` env var (default ``INFO``).
File handler always captures DEBUG+; stderr handler always WARNING+. So setting
``BOOTH_LOG_LEVEL=DEBUG`` adds forensic detail to the file without flooding
journald.
"""

import logging
import logging.handlers
import os
import sys

LOG_FILE = "/var/log/photobooth.log"
FILE_BYTES = 10 * 1024 * 1024
FILE_BACKUPS = 5
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Wire up the ``photobooth.*`` logger tree. Idempotent."""
    root = logging.getLogger("photobooth")
    if getattr(root, "_photobooth_configured", False):
        return

    requested = os.environ.get("BOOTH_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, requested, None)
    bad_level = None
    if not isinstance(level, int):
        bad_level = requested
        level = logging.INFO
    root.setLevel(level)

    fmt = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    try:
        file_h = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=FILE_BYTES, backupCount=FILE_BACKUPS
        )
        file_h.setLevel(logging.DEBUG)
        file_h.setFormatter(fmt)
        root.addHandler(file_h)
    except OSError as exc:
        sys.stderr.write(f"photobooth: file logging disabled: {exc}\n")

    stderr_h = logging.StreamHandler(sys.stderr)
    stderr_h.setLevel(logging.WARNING)
    stderr_h.setFormatter(fmt)
    root.addHandler(stderr_h)

    root._photobooth_configured = True  # type: ignore[attr-defined]

    if bad_level:
        root.warning("Invalid BOOTH_LOG_LEVEL=%r — falling back to INFO", bad_level)
