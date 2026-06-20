"""Tests for the v0.5.0 Phase 2 parallel-photo-display behaviour.

Pre-Phase-2, ``_take_one_shot`` awaited the reaction phrase on the LED
panel before returning. ``_review_shot`` then ran ``copy_to_last_shot``
and ``display_url(REVIEW_URL)``, so the photo only appeared on screen
*after* the phrase finished scrolling. Total perceived delay: ~3–5 s.

Phase 2 restructures so:

1. ``_take_one_shot`` launches the reaction phrase as a background task
   on ``self._phrase_task`` and returns immediately.
2. The caller runs ``_review_shot``, which navigates to ``REVIEW_URL``
   while the phrase continues scrolling in parallel.
3. ``_review_shot`` cancels/awaits ``self._phrase_task`` after the user
   decision so the panel is idle at the next state transition.

This test pins (2): ``display_url(REVIEW_URL)`` is invoked before the
phrase-scroll task records its first ``asyncio.sleep`` — i.e. the kiosk
navigation is dispatched while the phrase is still mid-scroll.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# ``booth_main`` does ``import board`` at module top — stub before import.
sys.modules.setdefault("board", MagicMock())

from photobooth.booth_main import REVIEW_URL, PhotoBooth  # noqa: E402


@pytest.fixture
def booth():
    """A bare ``PhotoBooth`` with hardware/IO swapped for mocks."""
    b = PhotoBooth()
    b.rpi = MagicMock()
    b.rpi.copy_to_last_shot = MagicMock()
    b._flush_events = AsyncMock()
    b.panel = MagicMock()
    b.camera = MagicMock()
    return b


async def test_display_url_invoked_before_phrase_first_sleep(booth):
    """Navigation must be dispatched while the phrase is still scrolling.

    The phrase task is created in ``_take_one_shot`` but does not run
    until the event loop picks it up. ``_review_shot`` then enters
    ``display_url`` synchronously (the coroutine body runs before any
    ``await`` yields control). The test records the first event each
    function emits and asserts the display-url event precedes the
    phrase's first sleep.
    """
    timeline = []

    async def scroll_for_duration(text, duration_s, color=None):
        await asyncio.sleep(0)

    async def reaction_scroll(text, speed=None, count=None):
        # Phrase scroll — runs as the background task. Record entry, then
        # yield so we can observe whether display_url ran first.
        timeline.append("phrase_enter")
        await asyncio.sleep(0)
        timeline.append("phrase_after_sleep")

    async def twinkle(count=30):
        await asyncio.sleep(0)

    async def capture_async():
        await asyncio.sleep(0)
        return "/tmp/fake_capture.jpg"

    async def display_url(url):
        # Record on entry. The very first line of the coroutine body
        # runs synchronously when awaited, before any yield — so if
        # phrase_enter appears before this, the parallel invariant is
        # broken.
        timeline.append(("display_url", url))
        await asyncio.sleep(0)

    booth.panel.scroll_for_duration = scroll_for_duration
    booth.panel.scroll = reaction_scroll
    booth.panel.twinkle = twinkle
    booth.panel.clear = MagicMock()
    booth.camera.capture_async = capture_async
    booth.rpi.display_url = display_url
    # next_event returns a "keep" decision (GREEN button maps to KEEP in
    # booth_main) so _review_shot exits promptly without a real button.
    booth.rpi.next_event = AsyncMock(return_value="green")
    # _compress_image touches disk — short-circuit for the fake path.
    booth._compress_image = lambda *a, **kw: None

    image_path = await booth._take_one_shot()
    await booth._review_shot(image_path)

    # Locate the display_url event and the first phrase event.
    display_idx = next(
        (i for i, e in enumerate(timeline) if isinstance(e, tuple) and e[0] == "display_url"),
        None,
    )
    phrase_idx = next(
        (i for i, e in enumerate(timeline) if e == "phrase_enter"),
        None,
    )

    assert display_idx is not None, f"display_url never invoked; timeline={timeline}"
    assert phrase_idx is not None, f"phrase scroll never ran; timeline={timeline}"

    # The display_url URL must target REVIEW_URL. Phase 7 routes the
    # call through ``display_url_with_context``, which appends
    # ``?mode=single&total=1`` for a no-template booth, so only the
    # base URL is pinned here.
    assert timeline[display_idx][1].startswith(REVIEW_URL)

    # The core Phase 2 invariant: display_url runs before the phrase
    # task's first sleep yields back to the loop.
    assert display_idx < phrase_idx, (
        "display_url(REVIEW_URL) must be invoked before the phrase "
        f"scroll's first sleep. timeline={timeline}"
    )


async def test_review_shot_cancels_phrase_task_before_returning(booth):
    """A long-running phrase task must be cancelled by _review_shot.

    Without the cleanup, a slow phrase would still be on the panel when
    the caller transitions to the next state (e.g. a series countdown),
    producing overlapping scrolls. Verify the task is done by the time
    ``_review_shot`` returns.
    """

    async def scroll_for_duration(text, duration_s, color=None):
        await asyncio.sleep(0)

    async def long_phrase(text, speed=None, count=None):
        # Simulate a phrase that would outlast the review window.
        await asyncio.sleep(60)

    async def twinkle(count=30):
        await asyncio.sleep(0)

    async def capture_async():
        return "/tmp/fake_capture.jpg"

    booth.panel.scroll_for_duration = scroll_for_duration
    booth.panel.scroll = long_phrase
    booth.panel.twinkle = twinkle
    booth.panel.clear = MagicMock()
    booth.camera.capture_async = capture_async
    booth.rpi.display_url = AsyncMock()
    booth.rpi.next_event = AsyncMock(return_value="green")
    booth._compress_image = lambda *a, **kw: None

    image_path = await booth._take_one_shot()
    phrase_task = booth._phrase_task
    assert phrase_task is not None and not phrase_task.done()

    await booth._review_shot(image_path)

    assert phrase_task.done(), "phrase task should be done after _review_shot returns"
    assert phrase_task.cancelled(), "phrase task should have been cancelled"
    assert booth._phrase_task is None, "_review_shot should clear _phrase_task"


async def test_review_shot_without_phrase_task_does_not_raise(booth):
    """Tests that drive _review_shot directly must keep working.

    ``test_series_flow.py`` invokes ``_review_shot`` without going
    through ``_take_one_shot``, so ``_phrase_task`` is never set. The
    cleanup must be a no-op in that case.
    """
    booth.rpi.display_url = AsyncMock()
    booth.rpi.next_event = AsyncMock(return_value="green")

    # No _phrase_task on the booth — calling _review_shot must not raise.
    result = await booth._review_shot("/tmp/fake_capture.jpg")
    assert result == "keep"
