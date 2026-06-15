"""Tests for ``Neopixel.scroll_for_duration`` (v0.5.0 Phase 1).

The new helper times each scroll so the total wall-clock pass equals the
caller's target duration, rather than tuning per-frame ``speed`` for each
label. These tests pin that contract: patch ``asyncio.sleep``, run
``scroll_for_duration``, sum the recorded delays, and assert the total is
within ±10% of the requested duration.

Hardware is stubbed at import time — the CircuitPython ``board`` and
``neopixel`` modules only resolve on a Raspberry Pi with Adafruit-Blinka
installed. ``Neopixel`` is then instantiated without ``__init__`` so the
underlying ``np`` pixel buffer is a MagicMock; the scroll loop's pixel
writes go to the mock while the timing path runs exactly as in production.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

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


@pytest.mark.parametrize(
    "text,duration",
    [
        ("3...", 0.4),
        ("2...", 0.4),
        ("1...", 0.4),
        ("Smile! :D", 0.8),
    ],
)
async def test_scroll_for_duration_sums_within_tolerance(text, duration):
    panel = _make_panel()
    delays = []

    async def fake_sleep(t):
        delays.append(t)

    with patch("photobooth.neopixel.asyncio.sleep", fake_sleep):
        await panel.scroll_for_duration(text=text, duration_s=duration)

    assert delays, "scroll_for_duration should issue at least one sleep"
    total = sum(delays)
    # Per-frame speed = duration / frames, summed over `frames` frames ⇒
    # total ≈ duration. ±10% slack covers rounding on small frame counts.
    tolerance = duration * 0.10
    assert abs(total - duration) <= tolerance, (
        f"Total sleep {total:.4f}s not within ±10% of {duration}s "
        f"(frames={len(delays)}, per_frame={delays[0]:.5f}s)"
    )


async def test_scroll_for_duration_per_frame_speed_is_uniform():
    """Each frame sleeps the same amount — uniform-cadence scroll."""
    panel = _make_panel()
    delays = []

    async def fake_sleep(t):
        delays.append(t)

    with patch("photobooth.neopixel.asyncio.sleep", fake_sleep):
        await panel.scroll_for_duration(text="3...", duration_s=0.4)

    assert len(set(delays)) == 1, f"Non-uniform per-frame sleep: {set(delays)}"
