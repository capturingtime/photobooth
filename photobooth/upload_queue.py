"""Persistent upload queue for photobooth (v0.5.0 Phase 6).

When the booth captures a shot while internet is down (or S3 is
flapping), the upload is deferred to this queue and the QR code on the
printed receipt still works because the S3 key is determined client-side
(see ``Uploader.make_key`` / ``Uploader.public_url``). A background worker
drains the queue once ``HealthMonitor`` reports ``net_www`` ready again.

Storage is a JSON file (default ``/var/lib/photobooth/upload_queue.json``)
written via ``state_store.save_json_atomic`` so a crash mid-write never
leaves a half-written queue. Every public method opens, mutates, and
closes the file — no long-held handles, no in-memory authoritative copy.
This matches the Phase 5 ``resume.json`` discipline so both files behave
the same way across an abrupt power loss.

The ``QueueItem`` record carries the data the worker needs to back off
sanely on repeated failures: ``attempts``, ``last_error``, and
``last_attempted_at``. Those survive across reboots so the booth doesn't
"forget" that an item has been failing for an hour after a restart.
"""

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from photobooth import state_store

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    """A single deferred upload.

    ``key`` is the S3 object key (deterministic client-side — Uploader
    callers stash it so the printed QR always points at the same path,
    regardless of when the upload eventually lands).

    ``image_path`` is the local file the worker uploads. The worker
    leaves the file alone on the booth — Phase 6 does not delete local
    captures after successful upload.
    """

    key: str
    image_path: str
    enqueued_at: float = field(default_factory=time.time)
    attempts: int = 0
    last_error: Optional[str] = None
    last_attempted_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "QueueItem":
        return cls(
            key=data["key"],
            image_path=data["image_path"],
            enqueued_at=data.get("enqueued_at", time.time()),
            attempts=data.get("attempts", 0),
            last_error=data.get("last_error"),
            last_attempted_at=data.get("last_attempted_at"),
        )


class UploadQueue:
    """JSON-backed FIFO queue for deferred S3 uploads.

    ``state_path`` is the on-disk location of the queue file. The parent
    directory must exist (provisioning creates ``/var/lib/photobooth``).

    The on-disk shape is a JSON object ``{"items": [QueueItem.to_dict(), ...]}``
    rather than a bare list — a top-level object leaves room for future
    metadata (schema version, last-drain timestamp) without a migration.
    """

    def __init__(self, state_path: str):
        self._state_path = state_path

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    def _load_items(self) -> List[QueueItem]:
        data = state_store.load_json(self._state_path)
        raw = data.get("items", []) if data else []
        return [QueueItem.from_dict(item) for item in raw]

    def _save_items(self, items: List[QueueItem]) -> None:
        state_store.save_json_atomic(
            self._state_path,
            {"items": [item.to_dict() for item in items]},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, key: str, image_path: str) -> QueueItem:
        """Append a new item to the queue and persist atomically.

        Returns the ``QueueItem`` so callers can log or inspect the
        newly enqueued record. Duplicate ``key`` entries are allowed —
        the queue does not dedupe; it is the caller's responsibility to
        avoid double-enqueue.
        """
        items = self._load_items()
        item = QueueItem(key=key, image_path=image_path)
        items.append(item)
        self._save_items(items)
        logger.info("Upload queued: key=%s file=%s depth=%d", key, image_path, len(items))
        return item

    def list(self) -> List[QueueItem]:
        """Return all items in queue order (oldest first)."""
        return self._load_items()

    def peek(self) -> Optional[QueueItem]:
        """Return the head item without removing it, or None if empty."""
        items = self._load_items()
        return items[0] if items else None

    def pop(self, key: str) -> bool:
        """Remove the first item matching ``key``. Returns True if removed.

        Match-by-key (not by index) so a re-entrant worker can't pop the
        wrong item after a refresh changed the head. If no item matches,
        returns False and leaves the file untouched.
        """
        items = self._load_items()
        for i, item in enumerate(items):
            if item.key == key:
                items.pop(i)
                self._save_items(items)
                logger.info("Upload popped: key=%s depth=%d", key, len(items))
                return True
        logger.debug("Upload pop miss: key=%s not in queue", key)
        return False

    def mark_attempt(self, key: str, error: Optional[str]) -> bool:
        """Record an attempt against the first item matching ``key``.

        Increments ``attempts``, stamps ``last_attempted_at`` to now,
        and stores ``error`` (None on the rare success-followed-by-pop-
        failure path). Returns True if the item was found.
        """
        items = self._load_items()
        for item in items:
            if item.key == key:
                item.attempts += 1
                item.last_attempted_at = time.time()
                item.last_error = error
                self._save_items(items)
                logger.debug(
                    "Upload attempt recorded: key=%s attempts=%d error=%s",
                    key,
                    item.attempts,
                    error,
                )
                return True
        return False

    def __len__(self) -> int:
        return len(self._load_items())
