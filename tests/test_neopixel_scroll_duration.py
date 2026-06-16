"""Tests for ``Neopixel.scroll_for_duration`` (v0.5.0 Phase 1, post-hotfix).

The original Phase 1 implementation derived per-frame ``speed`` from
``duration_s / frames`` and then slept that fixed amount per frame. That
math ignored the per-frame cost of ``np.show()`` (≈10-15ms on the live Pi
NeoPixel), so each label actually took ~2.5× the requested wall-clock
duration. The current implementation paces with absolute per-frame
deadlines so the total pass fits ``duration_s`` when rendering can keep
up, and gracefully degrades to "as fast as the hardware allows" when it
cannot.

These tests pin both behaviors. They run real timing (no
``asyncio.sleep`` mock) because the contract is wall-clock based; the
``Neopixel`` instance is built without ``__init__`` so the pixel buffer
is a MagicMock and no hardware is required.

Hardware and font are stubbed: CircuitPython ``board`` / ``neopixel`` only
resolve on a Pi with Adafruit-Blinka, and ``draw_text`` depends on
``ImageFont.getsize`` which was removed in Pillow ≥10. The tests
construct a PIL Image of a known width directly and pass it in, so the
timing path runs without touching font rendering.
"""

import sys
import time
from unittest.mock import MagicMock

import pytest
from PIL import Image

sys.modules.setdefault("board", MagicMock())
sys.modules.setdefault("neopixel", MagicMock())

from photobooth.neopixel import Neopixel  # noqa: E402 — post-stub import


def _make_panel(rows: int = 8, cols: int = 32) -> Neopixel:
    """Build a Neopixel with a mocked pixel buffer (no hardware required)."""
    panel = Neopixel.__new__(Neopixel)
    panel.name = "test"
    panel.rows = rows
    panel.cols = cols
    panel.num_px = rows * cols
    panel.np = MagicMock()
    return panel


def _image_with_frame_count(frames: int, cols: int = 32, rows: int = 8) -> Image.Image:
    """Build a PIL Image sized so ``image.width - cols == frames``."""
    return Image.new("P", (cols + frames, rows), 0)


@pytest.mark.parametrize("duration", [0.30, 0.40])
async def test_scroll_for_duration_wall_clock_matches_target(duration):
    """With negligible per-frame rendering cost, total pass ≈ duration_s.

    ±20% slack on the upper side accommodates OS scheduler jitter; the
    lower bound is tight because deadline-paced sleeps should not finish
    early when rendering is faster than the per-frame budget.
    """
    panel = _make_panel()
    image = _image_with_frame_count(frames=56)  # matches "3..." on the Pi
    start = time.perf_counter()
    await panel.scroll_for_duration(text=image, duration_s=duration)
    elapsed = time.perf_counter() - start
    assert (
        duration * 0.85 <= elapsed <= duration * 1.20
    ), f"elapsed {elapsed:.3f}s outside expected window for duration={duration}s"


async def test_scroll_for_duration_degrades_under_slow_show():
    """When ``np.show()`` is slower than the per-frame budget, total wall-clock
    is bounded by render time — deadline pacing must skip remaining sleeps
    rather than add them on top of late frames.

    Old (broken) behavior: each late frame added a full ``duration_s/frames``
    sleep on top of rendering cost, so total ≈ render_time + duration_s.
    New behavior: total ≈ render_time (sleeps go to 0 once behind schedule).
    """
    panel = _make_panel()
    # Simulate ~15ms-per-frame Pi NeoPixel render latency by blocking inside
    # ``np.show()``. 56 frames × 15ms ≈ 840ms render budget.
    panel.np.show = MagicMock(side_effect=lambda: time.sleep(0.015))
    image = _image_with_frame_count(frames=56)
    start = time.perf_counter()
    await panel.scroll_for_duration(text=image, duration_s=0.30)
    elapsed = time.perf_counter() - start
    # Render time alone is ~0.84s. The old per-frame-sleep bug would add
    # 0.30s on top → ~1.14s. The new code must NOT add that extra delay.
    assert elapsed < 1.05, f"elapsed {elapsed:.3f}s — deadline pacing failed to skip stale sleeps"
    # Sanity: render side-effect ran (not the instant-return path).
    assert elapsed > 0.50, f"elapsed {elapsed:.3f}s — render side-effect didn't run"


async def test_scroll_for_duration_zero_frames_is_safe():
    """A text image narrower than ``cols`` produces no frames; must not loop."""
    panel = _make_panel()
    tiny = Image.new("P", (8, 8), 0)
    result = await panel.scroll_for_duration(text=tiny, duration_s=0.1)
    assert result is True
