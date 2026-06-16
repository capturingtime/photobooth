"""Tests for ``PhotoBooth._upload_queue_worker`` (v0.5.0 Phase 6).

Pinned behaviors:

1. With internet ready, the worker drains a seeded queue, calling
   ``Uploader.upload`` once per item and popping each on success.
2. With internet unavailable, the worker does not call upload at all —
   it backs off and waits for HealthMonitor to flip net_www back to
   ready.
3. On a failed upload, the worker calls ``health._probe_once("net_www")``
   so the recheck loop owns the next ready-state transition.

The worker is a forever-loop; tests bound it by patching
``asyncio.sleep`` to ``CancelledError`` after the work we care about
has happened (so the loop exits cleanly).
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("board", MagicMock())

from photobooth import booth_main  # noqa: E402
from photobooth.booth_main import PhotoBooth  # noqa: E402
from photobooth.upload_queue import UploadQueue  # noqa: E402


@pytest.fixture
def booth(tmp_path, monkeypatch):
    queue_path = str(tmp_path / "upload_queue.json")
    monkeypatch.setattr(booth_main, "UPLOAD_QUEUE_PATH", queue_path)

    b = PhotoBooth()
    b._upload_queue = UploadQueue(queue_path)
    b.uploader = MagicMock()
    b.uploader.upload = AsyncMock()

    # HealthMonitor stub: ``is_ready`` and ``_probe_once`` controllable.
    b.health = MagicMock()
    b.health.is_ready = MagicMock(return_value=True)
    b.health._probe_once = AsyncMock()
    return b


async def _run_worker_briefly(booth, *, max_iterations=20):
    """Run ``_upload_queue_worker`` until the queue empties OR until
    ``max_iterations`` sleeps elapse, then cancel.

    We patch ``asyncio.sleep`` so the worker loop ticks instantly. Once
    the desired terminal condition is met (or iteration cap), the next
    sleep raises ``CancelledError`` so the worker exits via the
    cancellation path.
    """
    sleeps = {"count": 0}

    async def fake_sleep(_):
        sleeps["count"] += 1
        if sleeps["count"] >= max_iterations:
            raise asyncio.CancelledError
        # yield to other tasks
        await asyncio.sleep(0)

    # Patch the module's view of asyncio.sleep — the worker imports
    # ``asyncio`` at top level so we monkeypatch the module attribute.
    real_sleep = booth_main.asyncio.sleep
    booth_main.asyncio.sleep = fake_sleep
    try:
        with pytest.raises(asyncio.CancelledError):
            await booth._upload_queue_worker()
    finally:
        booth_main.asyncio.sleep = real_sleep


# ---------------------------------------------------------------------------
# Drain path
# ---------------------------------------------------------------------------


async def test_worker_drains_queue_when_net_is_ready(booth):
    booth._upload_queue.enqueue("k1", "/p/a.jpg")
    booth._upload_queue.enqueue("k2", "/p/b.jpg")

    await _run_worker_briefly(booth, max_iterations=10)

    # Both items uploaded exactly once.
    assert booth.uploader.upload.await_count == 2
    upload_args = [c.kwargs for c in booth.uploader.upload.await_args_list]
    assert {a["key"] for a in upload_args} == {"k1", "k2"}
    # Queue is empty.
    assert booth._upload_queue.list() == []


async def test_worker_skips_upload_when_net_not_ready(booth):
    booth._upload_queue.enqueue("k1", "/p/a.jpg")
    booth.health.is_ready = MagicMock(return_value=False)

    await _run_worker_briefly(booth, max_iterations=5)

    booth.uploader.upload.assert_not_awaited()
    # Item stays queued so it drains later.
    assert len(booth._upload_queue.list()) == 1


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


async def test_worker_marks_attempt_and_reprobes_on_failure(booth):
    booth._upload_queue.enqueue("k1", "/p/a.jpg")
    booth.uploader.upload = AsyncMock(side_effect=RuntimeError("S3 down"))

    await _run_worker_briefly(booth, max_iterations=5)

    # Item still queued with attempts recorded.
    items = booth._upload_queue.list()
    assert len(items) == 1
    assert items[0].attempts >= 1
    assert "S3 down" in (items[0].last_error or "")
    # net_www was re-probed after the failure so recheck_loop owns
    # the next ready-state transition.
    assert booth.health._probe_once.await_count >= 1
    assert booth.health._probe_once.await_args.args == ("net_www",)


async def test_worker_handles_missing_net_www_component_gracefully(booth):
    """If ``net_www`` was never registered (dev environment), ``is_ready``
    raises ``KeyError``. The worker must treat that as "not ready" and
    back off, not crash.
    """
    booth._upload_queue.enqueue("k1", "/p/a.jpg")
    booth.health.is_ready = MagicMock(side_effect=KeyError("net_www"))

    await _run_worker_briefly(booth, max_iterations=5)

    booth.uploader.upload.assert_not_awaited()
    assert len(booth._upload_queue.list()) == 1


# ---------------------------------------------------------------------------
# Empty queue
# ---------------------------------------------------------------------------


async def test_worker_idles_on_empty_queue(booth):
    await _run_worker_briefly(booth, max_iterations=5)
    booth.uploader.upload.assert_not_awaited()
