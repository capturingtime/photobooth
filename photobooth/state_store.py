"""Atomic JSON file storage for photobooth runtime state (v0.5.0 Phase 5).

Used by Phase 5's unavailable-mode recovery to persist a resume record
(``/var/lib/photobooth/resume.json``) so a mid-capture failure can resume
at the exact step the booth was on, and by Phase 6's upload queue
(``/var/lib/photobooth/upload_queue.json``).

Design rules:

* No long-held file handles. Every read and every write opens the file,
  does its work, and closes the handle. This keeps the state safe across
  unexpected restarts of the booth service.
* Writes are atomic: data is serialized to ``<path>.tmp`` first, the
  temp file is fsync'd, then ``os.replace`` swaps it onto the target
  path. A crash mid-write leaves the previous (good) file intact.
* ``load_json`` returns ``{}`` for a missing file instead of raising.
  Callers can treat "no state" and "fresh start" uniformly.
"""

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


def load_json(path: str) -> Dict[str, Any]:
    """Return the JSON contents of ``path``, or ``{}`` if the file is missing.

    Other errors (malformed JSON, permission failures) propagate. The
    booth's resume path treats a missing file as "no resume needed";
    treating a corrupted file the same way would mask real bugs.
    """
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json_atomic(path: str, data: Dict[str, Any]) -> None:
    """Serialize ``data`` to ``path`` via a fsync'd temp file + ``os.replace``.

    The target directory must already exist (created by provisioning).
    On any failure during the temp-file phase, the temp file is removed
    so a retry can write fresh. The previous file at ``path`` is never
    touched until the swap.
    """
    tmp_path = path + ".tmp"
    parent = os.path.dirname(path) or "."
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise
    os.replace(tmp_path, path)
    # fsync the directory so the rename is durable across power loss.
    try:
        dir_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        logger.debug("save_json_atomic: directory fsync skipped (%s)", exc)


def delete_if_exists(path: str) -> None:
    """Remove ``path`` if it exists; no-op otherwise. Used to clear resume.json."""
    try:
        os.remove(path)
    except FileNotFoundError:
        return
