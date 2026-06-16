"""Tests for ``photobooth.upload_queue`` (v0.5.0 Phase 6).

Contract surface:

* ``enqueue`` / ``list`` / ``peek`` / ``pop`` round-trip via the JSON
  file on disk; no in-memory authoritative copy survives between calls.
* ``mark_attempt`` updates the matching item without losing the queue
  ordering or other items' state.
* Atomic write semantics — a crash mid-write (simulated by patching
  ``os.replace`` in ``state_store``) must leave the previous on-disk
  queue intact.
"""

import os

import pytest

from photobooth import state_store
from photobooth.upload_queue import QueueItem, UploadQueue


@pytest.fixture
def queue_path(tmp_path):
    return str(tmp_path / "upload_queue.json")


@pytest.fixture
def queue(queue_path):
    return UploadQueue(queue_path)


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------


def test_empty_queue_has_no_items(queue):
    assert queue.list() == []
    assert queue.peek() is None
    assert len(queue) == 0


def test_enqueue_persists_to_disk(queue, queue_path):
    queue.enqueue("booth/k1", "/opt/booth_images/a.jpg")

    # New instance reads the same file — exercises the "no in-memory
    # state" rule.
    fresh = UploadQueue(queue_path)
    items = fresh.list()
    assert len(items) == 1
    assert items[0].key == "booth/k1"
    assert items[0].image_path == "/opt/booth_images/a.jpg"


def test_enqueue_preserves_fifo_order(queue):
    queue.enqueue("k1", "/p/a.jpg")
    queue.enqueue("k2", "/p/b.jpg")
    queue.enqueue("k3", "/p/c.jpg")

    keys = [item.key for item in queue.list()]
    assert keys == ["k1", "k2", "k3"]
    assert queue.peek().key == "k1"


def test_pop_removes_matching_item_only(queue):
    queue.enqueue("k1", "/p/a.jpg")
    queue.enqueue("k2", "/p/b.jpg")
    queue.enqueue("k3", "/p/c.jpg")

    assert queue.pop("k2") is True

    keys = [item.key for item in queue.list()]
    assert keys == ["k1", "k3"]


def test_pop_missing_key_returns_false_and_leaves_queue_intact(queue):
    queue.enqueue("k1", "/p/a.jpg")
    assert queue.pop("nope") is False
    assert [i.key for i in queue.list()] == ["k1"]


def test_mark_attempt_records_failure_metadata(queue):
    queue.enqueue("k1", "/p/a.jpg")
    queue.enqueue("k2", "/p/b.jpg")

    assert queue.mark_attempt("k2", "timeout") is True
    assert queue.mark_attempt("k2", "still timeout") is True

    items = queue.list()
    k1, k2 = items[0], items[1]

    # k1 untouched.
    assert k1.attempts == 0
    assert k1.last_error is None
    # k2 records both attempts + latest error.
    assert k2.attempts == 2
    assert k2.last_error == "still timeout"
    assert k2.last_attempted_at is not None


def test_mark_attempt_missing_key_returns_false(queue):
    queue.enqueue("k1", "/p/a.jpg")
    assert queue.mark_attempt("nope", "err") is False


# ---------------------------------------------------------------------------
# Crash-safety
# ---------------------------------------------------------------------------


def test_atomic_write_survives_crash_during_replace(queue, queue_path, monkeypatch):
    """Simulating a power loss mid-``os.replace`` must leave the prior
    queue intact so the worker doesn't lose items on a bad shutdown.

    Pattern matches ``test_state_store.test_save_json_atomic_crash_during_replace_preserves_original``
    — the upload queue inherits the property because it flows through
    ``state_store.save_json_atomic``.
    """
    queue.enqueue("good", "/p/good.jpg")

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated mid-replace power loss")

    monkeypatch.setattr(state_store.os, "replace", boom)
    with pytest.raises(OSError):
        queue.enqueue("bad", "/p/bad.jpg")

    monkeypatch.setattr(state_store.os, "replace", real_replace)
    keys = [item.key for item in queue.list()]
    assert keys == ["good"]  # bad was not committed


def test_queue_item_round_trip_dict():
    """Defensive: serializing an item and rebuilding it produces an equal
    record. Protects the JSON shape from accidental field renames.
    """
    item = QueueItem(key="k1", image_path="/p/a.jpg", attempts=3, last_error="x")
    rebuilt = QueueItem.from_dict(item.to_dict())
    assert rebuilt.key == item.key
    assert rebuilt.image_path == item.image_path
    assert rebuilt.attempts == item.attempts
    assert rebuilt.last_error == item.last_error
