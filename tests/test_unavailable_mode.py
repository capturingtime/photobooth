"""Tests for ``PhotoBooth._enter_unavailable`` and the camera-failure
recovery wiring (v0.5.0 Phase 5).

Two contracts are pinned:

1. ``_enter_unavailable`` navigates to ``UNAVAILABLE_URL``, starts a
   continuous (count=999) RED scroll on the panel, and awaits
   ``HealthMonitor.wait_until_ready`` with no timeout.
2. ``_take_one_shot`` catches a camera exception, persists resume state
   via ``state_store``, enters unavailable mode, and returns ``None`` so
   the caller (``_run_series`` / ``_run_single``) routes the user to the
   right recovery screen.

Hardware/IO is stubbed identically to ``test_series_flow.py`` — the
``board`` import at the top of ``booth_main`` is stubbed before import.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("board", MagicMock())

from photobooth import booth_main, state_store  # noqa: E402
from photobooth.booth_main import (  # noqa: E402
    CAMERA_UNAVAILABLE_TEXT,
    PRINTER_UNAVAILABLE_TEXT,
    UNAVAILABLE_SCROLL_COLOR,
    UNAVAILABLE_URL,
    PhotoBooth,
)


@pytest.fixture
def booth(tmp_path, monkeypatch):
    """A ``PhotoBooth`` with hardware stubs and a tmp resume-state path."""
    monkeypatch.setattr(booth_main, "RESUME_STATE_PATH", str(tmp_path / "resume.json"))

    b = PhotoBooth()
    b.rpi = MagicMock()
    b.rpi.display_url = AsyncMock()
    b.rpi.copy_to_last_shot = MagicMock()

    b.panel = MagicMock()
    b.panel.clear = MagicMock()
    # scroll runs forever until cancelled.
    b.panel.scroll = AsyncMock(side_effect=lambda *a, **k: asyncio.sleep(3600))
    b.panel.scroll_for_duration = AsyncMock()
    b.panel.twinkle = AsyncMock()

    b._flush_events = AsyncMock()

    # Health monitor with a controllable wait_until_ready.
    b.health = MagicMock()
    b.health.wait_until_ready = AsyncMock(return_value=True)

    return b


# ---------------------------------------------------------------------------
# _enter_unavailable
# ---------------------------------------------------------------------------


async def test_enter_unavailable_navigates_and_scrolls(booth):
    await booth._enter_unavailable("camera", CAMERA_UNAVAILABLE_TEXT)

    booth.rpi.display_url.assert_awaited_once_with(UNAVAILABLE_URL)
    # The scroll call captures the params we care about: continuous + RED.
    assert booth.panel.scroll.call_args is not None
    kwargs = booth.panel.scroll.call_args.kwargs
    assert kwargs["text"] == CAMERA_UNAVAILABLE_TEXT
    assert kwargs["count"] == 999
    assert kwargs["color"] == UNAVAILABLE_SCROLL_COLOR

    booth.health.wait_until_ready.assert_awaited_once_with("camera", timeout=None)
    booth.panel.clear.assert_called_once()


async def test_enter_unavailable_uses_printer_text(booth):
    await booth._enter_unavailable("printer", PRINTER_UNAVAILABLE_TEXT)

    kwargs = booth.panel.scroll.call_args.kwargs
    assert kwargs["text"] == PRINTER_UNAVAILABLE_TEXT
    booth.health.wait_until_ready.assert_awaited_once_with("printer", timeout=None)


async def test_enter_unavailable_clears_panel_even_if_wait_raises(booth):
    """If ``wait_until_ready`` itself raises (e.g. monitor goes away), the
    scroll task must still be cancelled and the panel cleared — otherwise
    the booth is left with a red error scroll on a screen that's about to
    be repurposed by the caller's exception handler.
    """
    booth.health.wait_until_ready = AsyncMock(side_effect=RuntimeError("oops"))
    with pytest.raises(RuntimeError):
        await booth._enter_unavailable("camera", CAMERA_UNAVAILABLE_TEXT)
    booth.panel.clear.assert_called_once()


# ---------------------------------------------------------------------------
# _take_one_shot — camera failure path
# ---------------------------------------------------------------------------


async def test_take_one_shot_camera_failure_enters_unavailable(booth, tmp_path):
    """When ``capture_async`` raises, the booth saves resume state, enters
    unavailable mode, and returns ``None``. The recovered camera is then
    available — but the retry is the caller's responsibility (so the
    series flow can decide whether to retake the same shot or cancel).
    """
    booth.camera = MagicMock()
    booth.camera.capture_async = AsyncMock(side_effect=RuntimeError("gphoto2 boom"))

    # Spy on _enter_unavailable so the test doesn't actually run the
    # full unavailable flow (already covered above).
    booth._enter_unavailable = AsyncMock()

    resume_ctx = {
        "mode": "series",
        "pending_step": "capture",
        "series_shots": ["a.jpg", "b.jpg"],
        "shot_index": 3,
        "total": 3,
        "template_name": "tpl",
    }
    result = await booth._take_one_shot(resume_context=resume_ctx)

    assert result is None
    booth._enter_unavailable.assert_awaited_once()
    args = booth._enter_unavailable.call_args.args
    assert args == ("camera", CAMERA_UNAVAILABLE_TEXT)

    # Resume state was written before the camera ran.
    persisted = state_store.load_json(booth_main.RESUME_STATE_PATH)
    assert persisted == resume_ctx


async def test_take_one_shot_camera_success_does_not_enter_unavailable(booth, tmp_path):
    booth.camera = MagicMock()
    booth.camera.capture_async = AsyncMock(return_value="/tmp/shot.jpg")
    booth._enter_unavailable = AsyncMock()
    booth._compress_image = MagicMock()

    result = await booth._take_one_shot(
        resume_context={
            "mode": "single",
            "pending_step": "capture",
            "template_name": None,
        }
    )

    assert result == "/tmp/shot.jpg"
    booth._enter_unavailable.assert_not_awaited()
