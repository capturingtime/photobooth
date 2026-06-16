"""Tests for mid-series camera-failure recovery and cross-process resume
(v0.5.0 Phase 5).

Two scenarios:

1. In-process mid-series recovery — capture shots 1 and 2 successfully,
   fail on shot 3, recover, expect:
   * resume.json persisted with shots 1+2 and shot_index=3
   * _enter_unavailable invoked with the camera component + scroll text
   * the booth routes to ``_series_capture_review`` so the user can press
     blue to retry shot 3 or red to cancel, with shots 1+2 still in memory

2. Cross-process resume from ``_resume_from`` — when a stored
   resume.json describes a series partway through, the booth navigates
   to the series_capture page with the right ``?shot=X&total=N&mode=series``
   query string and stages ``_pending_resume_shots`` for the next blue-
   button event to consume.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("board", MagicMock())

from photobooth import booth_main, state_store  # noqa: E402
from photobooth.booth_main import (  # noqa: E402
    CAMERA_UNAVAILABLE_TEXT,
    SERIES_CAPTURE_URL,
    PhotoBooth,
)


@pytest.fixture
def booth(tmp_path, monkeypatch):
    monkeypatch.setattr(booth_main, "RESUME_STATE_PATH", str(tmp_path / "resume.json"))
    monkeypatch.setattr(booth_main, "ACTIVE_TEMPLATE", "tpl")

    b = PhotoBooth()
    b.rpi = MagicMock()
    b.rpi.display_url = AsyncMock()
    b.rpi.copy_to_last_shot = MagicMock()

    b.panel = MagicMock()
    b.panel.clear = MagicMock()
    b.panel.scroll = AsyncMock(side_effect=lambda *a, **k: asyncio.sleep(3600))
    b.panel.scroll_for_duration = AsyncMock()
    b.panel.twinkle = AsyncMock()
    b._flush_events = AsyncMock()
    b._compress_image = MagicMock()

    b.health = MagicMock()
    b.health.wait_until_ready = AsyncMock(return_value=True)

    # 3-shot series template stub.
    b.strip = MagicMock()
    b.strip.shot_count = 3

    return b


# ---------------------------------------------------------------------------
# In-process mid-series recovery
# ---------------------------------------------------------------------------


async def test_mid_series_camera_failure_preserves_shots(booth, monkeypatch):
    """Shots 1-2 captured, shot 3 fails. Expected: resume.json holds the
    first two paths + ``shot_index=3``, ``_enter_unavailable`` fires with
    camera, and after recovery the user lands on ``_series_capture_review``
    with ``shots=["shot1.jpg", "shot2.jpg"]`` (matching the acceptance
    test "shots 1-2 preserved").
    """
    captures = ["shot1.jpg", "shot2.jpg"]
    fail_after = 2

    async def capture_or_fail():
        if len(booth.camera.captures_returned) >= fail_after:
            raise RuntimeError("camera unplugged")
        path = captures[len(booth.camera.captures_returned)]
        booth.camera.captures_returned.append(path)
        return path

    booth.camera = MagicMock()
    booth.camera.captures_returned = []
    booth.camera.capture_async = capture_or_fail

    # _review_shot always returns "keep" so series advances after each shot.
    booth._review_shot = AsyncMock(return_value="keep")

    # Spy on _enter_unavailable to short-circuit the wait.
    enter_calls = []

    async def fake_enter(component, scroll_text):
        enter_calls.append((component, scroll_text))

    booth._enter_unavailable = fake_enter

    # _series_capture_review is called between successful shots (with
    # ``last_decided`` set) AND after the camera-failure recovery (with
    # ``last_decided=None``). For the between-shots calls we return
    # "continue" so the series advances; on the post-failure call we
    # return "start_over" to end the test, and capture the shots state
    # then to verify shots 1-2 are preserved.
    captured_shots_at_review = []

    async def fake_review(shots, last_decided):
        if last_decided is None:
            captured_shots_at_review.append(list(shots))
            return "start_over"
        return "continue"

    booth._series_capture_review = fake_review

    result = await booth._run_series()

    assert result is None  # series cancelled at the recovery page
    # Camera was invoked for shot 1, shot 2, then raised on shot 3.
    assert booth.camera.captures_returned == ["shot1.jpg", "shot2.jpg"]
    # _enter_unavailable was called exactly once, with camera + the right text.
    assert enter_calls == [("camera", CAMERA_UNAVAILABLE_TEXT)]
    # The post-recovery review page sees shots 1-2 preserved.
    assert captured_shots_at_review == [["shot1.jpg", "shot2.jpg"]]

    # Resume state on disk reflects the failure point: 2 shots captured,
    # next shot is 3 of 3.
    persisted = state_store.load_json(booth_main.RESUME_STATE_PATH)
    assert persisted["mode"] == "series"
    assert persisted["series_shots"] == ["shot1.jpg", "shot2.jpg"]
    assert persisted["shot_index"] == 3
    assert persisted["total"] == 3


async def test_mid_series_recovery_continues_to_shot_3(booth):
    """After recovery, if the user presses blue (``_series_capture_review``
    returns ``"continue"``), ``_run_series`` retries shot 3 — the next
    ``capture_async`` succeeds and the strip composes with all 3 shots.
    """
    captures = ["shot1.jpg", "shot2.jpg", "shot3.jpg"]
    fail_once = {"done": False}

    async def capture_or_fail():
        if len(booth.camera.captures_returned) == 2 and not fail_once["done"]:
            fail_once["done"] = True
            raise RuntimeError("camera blip")
        path = captures[len(booth.camera.captures_returned)]
        booth.camera.captures_returned.append(path)
        return path

    booth.camera = MagicMock()
    booth.camera.captures_returned = []
    booth.camera.capture_async = capture_or_fail
    booth._review_shot = AsyncMock(return_value="keep")
    booth._enter_unavailable = AsyncMock()
    booth._series_capture_review = AsyncMock(return_value="continue")

    # Strip compose returns a final path so we can assert success.
    booth.strip.compose = MagicMock(return_value="/tmp/strip.jpg")

    # Avoid a real run_in_executor call — patch the running-loop method.
    async def fake_run_in_executor(_executor, fn, *args):
        return fn(*args)

    loop = asyncio.get_running_loop()
    orig = loop.run_in_executor
    loop.run_in_executor = fake_run_in_executor
    try:
        result = await booth._run_series()
    finally:
        loop.run_in_executor = orig

    assert result == "/tmp/strip.jpg"
    # All three shots eventually captured.
    assert booth.camera.captures_returned == ["shot1.jpg", "shot2.jpg", "shot3.jpg"]
    booth._enter_unavailable.assert_awaited_once()


# ---------------------------------------------------------------------------
# Cross-process resume from disk
# ---------------------------------------------------------------------------


async def test_resume_from_series_state_navigates_with_query_params(booth):
    state = {
        "mode": "series",
        "series_shots": ["shot1.jpg", "shot2.jpg"],
        "pending_step": "capture",
        "shot_index": 3,
        "total": 3,
        "template_name": "tpl",
    }

    booth._pending_resume_shots = []
    await booth._resume_from(state)

    assert booth._pending_resume_shots == ["shot1.jpg", "shot2.jpg"]
    booth.rpi.display_url.assert_awaited_once()
    url = booth.rpi.display_url.call_args.args[0]
    assert url.startswith(SERIES_CAPTURE_URL)
    assert "mode=series" in url
    assert "shot=3" in url
    assert "total=3" in url


async def test_resume_from_single_mode_clears_state(booth):
    """Single-shot has nothing partial worth resuming; if the state
    happens to be a single-shot record (or anything not series with
    shots), wipe it and return to normal startup.
    """
    state = {"mode": "single", "pending_step": "capture"}
    booth._pending_resume_shots = []
    # Pre-write a state file so we can verify it's deleted.
    state_store.save_json_atomic(booth_main.RESUME_STATE_PATH, state)

    await booth._resume_from(state)

    assert booth._pending_resume_shots == []
    assert state_store.load_json(booth_main.RESUME_STATE_PATH) == {}
    booth.rpi.display_url.assert_not_called()


async def test_resume_from_empty_state_is_noop(booth):
    booth._pending_resume_shots = []
    await booth._resume_from({})
    assert booth._pending_resume_shots == []
    booth.rpi.display_url.assert_not_called()
