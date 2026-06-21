"""Tests for the v0.5.0 Phase 1 countdown-to-shutter timing.

Pre-Phase-1, ``_take_one_shot`` awaited all four scrolls serially before
firing the camera, so button-press → shutter latency was the full
countdown + the camera's gphoto2 round-trip. Phase 1 restructures the
function so:

1. ``3...``, ``2...``, ``1...`` each scroll for 0.4 s (1.2 s subtotal).
2. ``capture_async()`` is dispatched as a task at the 1.2 s mark.
3. ``Smile! :D`` scrolls for 0.8 s in parallel with the camera capture,
   ending the visible countdown at the 2.0 s mark — within the ≤ 2.1 s
   stopwatch acceptance criterion on the booth.

This test drives a virtual clock advanced by the patched
``scroll_for_duration`` mock, so the timing assertion runs deterministically
without real waits. The mock ordering — append-to-timeline, yield, then
advance clock — mirrors real wall-clock behaviour: concurrent tasks
scheduled before the scroll observe the pre-scroll time, not the
post-scroll time.
"""

import asyncio
import sys
from unittest.mock import MagicMock

import pytest

# ``booth_main`` does ``import board`` at module top — stub before import.
sys.modules.setdefault("board", MagicMock())

from photobooth.booth_main import PhotoBooth  # noqa: E402 — post-stub import


@pytest.fixture
def booth():
    """A bare ``PhotoBooth`` with hardware/IO swapped for mocks."""
    b = PhotoBooth()
    b.rpi = MagicMock()
    b.panel = MagicMock()
    b.camera = MagicMock()
    return b


async def test_take_one_shot_countdown_timing(booth):
    clock = {"t": 0.0}
    timeline = []

    async def scroll_for_duration(text, duration_s, color=None):
        # Record start time BEFORE the yield so concurrent tasks scheduled
        # alongside this scroll observe the same sim-time we record here.
        timeline.append(("scroll", text, clock["t"]))
        await asyncio.sleep(0)
        clock["t"] += duration_s

    async def reaction_scroll(*args, **kwargs):
        # Post-capture phrase — outside the countdown window we measure.
        await asyncio.sleep(0)

    async def twinkle(count=30):
        # Fallback only triggers if capture lags past the Smile! scroll;
        # this test resolves capture promptly so twinkle stays unused.
        await asyncio.sleep(0)

    async def capture_async():
        timeline.append(("capture_called", "", clock["t"]))
        await asyncio.sleep(0)
        return "/tmp/fake_capture.jpg"

    booth.panel.scroll_for_duration = scroll_for_duration
    booth.panel.scroll = reaction_scroll
    booth.panel.twinkle = twinkle
    booth.panel.clear = MagicMock()
    booth.camera.capture_async = capture_async
    # ``_compress_image`` reads the captured file from disk — short-circuit
    # since the fake path doesn't exist.
    booth._compress_image = lambda *a, **kw: None

    await booth._take_one_shot()

    # Phase 2: the reaction phrase is now launched as a background task
    # on ``booth._phrase_task``. Drain it so the event loop closes cleanly
    # without a "Task was destroyed but it is pending" warning.
    phrase_task = getattr(booth, "_phrase_task", None)
    if phrase_task is not None:
        if not phrase_task.done():
            phrase_task.cancel()
        try:
            await phrase_task
        except asyncio.CancelledError:
            pass

    capture_events = [e for e in timeline if e[0] == "capture_called"]
    smile_events = [e for e in timeline if e[0] == "scroll" and "Smile" in e[1]]

    assert capture_events, "capture_async was never invoked"
    assert smile_events, "Smile! scroll was never started"

    capture_t = capture_events[0][2]
    smile_t = smile_events[0][2]

    # Phase 1 timeline: 3 × 0.4 s of countdown, then capture dispatch in
    # parallel with the 0.8 s "Smile!" scroll → end at the 2.0 s mark.
    target = 2.0
    tolerance = 0.10  # ≈ ±5 %
    assert abs(clock["t"] - target) <= tolerance, (
        f"Countdown ended at sim t={clock['t']:.3f}s, " f"expected {target}s ±{tolerance}s"
    )
    # capture_async must dispatch no later than Smile! starts — the entire
    # point of Phase 1 is to overlap the two.
    assert capture_t <= smile_t + 1e-6, (
        f"capture_async dispatched at sim t={capture_t:.3f}s; "
        f"expected ≤ Smile! start at t={smile_t:.3f}s"
    )
    # Capture should land at the 1.2 s mark (right after 3 / 2 / 1).
    assert (
        abs(capture_t - 1.2) <= 0.1
    ), f"capture_async dispatched at sim t={capture_t:.3f}s, expected 1.2s ±0.1s"
