"""Tests for ``PhotoBooth._series_capture_review``.

The between-shots page is the booth's most complex state-machine node:
multiple entry paths (from keep OR from redo), three valid button presses
(continue / cancel / show-last), and a re-review sub-flow that can mutate
the shot list. The bug history (show-last on a redone first shot was a
dead button; keep→show-last→redo skipped the countdown buffer) all came
from this region of the code, so these tests pin the contract down before
the next refactor regresses it.

Approach: instantiate ``PhotoBooth`` directly (no ``__init__``), set the
``rpi`` / ``panel`` / ``_flush_events`` attributes to mocks, and drive
``_series_capture_review`` with scripted button-event sequences. The
function under test is async, so ``asyncio_mode = "auto"`` in the project
``pyproject.toml`` discovers these without an explicit decorator.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# ``booth_main`` does ``import board`` at module top — only resolves on a
# Raspberry Pi with Adafruit-Blinka installed. Stub before import.
sys.modules.setdefault("board", MagicMock())

from photobooth.booth_main import (  # noqa: E402 — deliberate post-stub import
    KEEP_BUTTON,
    REDO_BUTTON,
    PhotoBooth,
)


def _event_script(events):
    """Build an async ``next_event()`` that pops from a scripted list.

    The returned callable carries a ``.consumed`` list so tests can assert
    the exact number of events processed. This is the only way to verify
    the buffer step that fires after a re-review (the function must consume
    one more event than the bare decision required) — without that check
    a regression that returned early would still pass the return-value
    assertion.
    """
    queue = list(events)
    consumed = []

    async def next_event():
        if not queue:
            pytest.fail("next_event called more times than scripted")
        e = queue.pop(0)
        consumed.append(e)
        return e

    next_event.consumed = consumed
    return next_event


@pytest.fixture
def booth():
    """A ``PhotoBooth`` with all hardware/IO calls stubbed.

    ``PhotoBooth`` has no ``__init__``; the attributes normally set up in
    ``run()`` and ``_startup()`` are assigned directly here so
    ``_series_capture_review`` can run without bringing up the rest of the
    booth. Each test sets ``booth.rpi.next_event`` to its own scripted
    sequence.
    """
    b = PhotoBooth()

    b.rpi = MagicMock()
    b.rpi.display_url = AsyncMock()
    b.rpi.copy_to_last_shot = MagicMock()  # called from _review_shot
    # rpi.next_event is set per-test

    # Scroll task is created via asyncio.create_task and cancelled in a
    # finally block. An infinite sleep is cancellable and avoids running
    # any real neopixel code.
    async def fake_scroll(*args, **kwargs):
        await asyncio.sleep(3600)

    b.panel = MagicMock()
    b.panel.scroll = fake_scroll

    # Real _flush_events awaits 0.1 s; in tests we want it instant.
    b._flush_events = AsyncMock()

    return b


async def _drain_cancelled_tasks():
    """Yield once so cancelled scroll tasks can wind down cleanly.

    Without this, the event loop closes while the cancelled scroll task
    is still pending, which produces "Task was destroyed but it is
    pending" warnings.
    """
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Trivial decisions: continue and start_over leave shots untouched
# ---------------------------------------------------------------------------


async def test_capture_returns_continue_without_mutating_shots(booth):
    booth.rpi.next_event = _event_script(["capture"])
    shots = ["shot1", "shot2"]

    result = await booth._series_capture_review(shots, last_decided="shot2")
    await _drain_cancelled_tasks()

    assert result == "continue"
    assert shots == ["shot1", "shot2"]


async def test_red_returns_start_over_without_mutating_shots(booth):
    booth.rpi.next_event = _event_script([REDO_BUTTON])
    shots = ["shot1"]

    result = await booth._series_capture_review(shots, last_decided="shot1")
    await _drain_cancelled_tasks()

    assert result == "start_over"
    assert shots == ["shot1"]


# ---------------------------------------------------------------------------
# Show-last decision-overrides: mutate shots, then RETURN TO THE PAGE
# (the buffer step is what these tests really pin down)
# ---------------------------------------------------------------------------


async def test_show_last_then_keep_on_redone_shot_appends(booth):
    """Original bug: redo on shot 1 left ``shots`` empty, so the GREEN
    button on the series_capture page no-op'd. New contract: the redone
    shot is reviewable and accepting it appends to ``shots``."""
    events = _event_script([KEEP_BUTTON, KEEP_BUTTON, "capture"])
    booth.rpi.next_event = events
    shots = []

    result = await booth._series_capture_review(shots, last_decided="shot1")
    await _drain_cancelled_tasks()

    assert result == "continue"
    assert shots == ["shot1"]
    # Third event ("capture") is the buffer press the user has to make on
    # the re-displayed series_capture page. If the function regresses and
    # advances straight to countdown after the re-review, the third event
    # is never consumed.
    assert len(events.consumed) == 3


async def test_show_last_then_redo_on_kept_shot_removes(booth):
    """Today's bug fix: keep shot 2 → show-last → redo on the re-review.
    The previously-kept shot must be removed AND the user must be brought
    back to the series_capture page (not straight to countdown)."""
    events = _event_script([KEEP_BUTTON, REDO_BUTTON, "capture"])
    booth.rpi.next_event = events
    shots = ["shot1", "shot2"]

    result = await booth._series_capture_review(shots, last_decided="shot2")
    await _drain_cancelled_tasks()

    assert result == "continue"
    assert shots == ["shot1"]
    # As above: if the buffer step regresses, the third event is unused
    # and this assertion fails before the return-value check would.
    assert len(events.consumed) == 3


# ---------------------------------------------------------------------------
# Re-affirming the original decision: shots unchanged, still buffer'd
# ---------------------------------------------------------------------------


async def test_show_last_then_keep_on_already_kept_shot_is_noop(booth):
    """Keep shot N → show-last → keep again. Shot already in ``shots``;
    nothing to append. User still ends up back on the series_capture
    page (buffer)."""
    events = _event_script([KEEP_BUTTON, KEEP_BUTTON, "capture"])
    booth.rpi.next_event = events
    shots = ["shotN"]

    result = await booth._series_capture_review(shots, last_decided="shotN")
    await _drain_cancelled_tasks()

    assert result == "continue"
    assert shots == ["shotN"]
    assert len(events.consumed) == 3


async def test_show_last_then_redo_on_already_redone_shot_is_noop(booth):
    """Redo on shot 1 → show-last → redo again. Shot already absent from
    ``shots``; nothing to remove. User still ends up back on the
    series_capture page (buffer)."""
    events = _event_script([KEEP_BUTTON, REDO_BUTTON, "capture"])
    booth.rpi.next_event = events
    shots = []

    result = await booth._series_capture_review(shots, last_decided="shot1")
    await _drain_cancelled_tasks()

    assert result == "continue"
    assert shots == []
    assert len(events.consumed) == 3
