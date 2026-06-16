"""Tests for the v0.5.0 Phase 7 URL-query-string bridge.

Series-mode display context — ``shot``, ``total``, ``mode`` — flows
from ``booth_main`` into Django templates via URL query parameters,
appended by ``PhotoBooth.display_url_with_context``. This file pins:

1. The helper itself: ``urlencode``s params and dispatches to
   ``self.rpi.display_url``; empty params leave the URL untouched.
2. ``_series_params``: derives ``mode``/``total`` from the active
   ``self.strip`` (a single-shot strip is still ``mode=single``).
3. The capture-flow callers (``_review_shot`` for last_capture and
   ``_series_capture_review`` for series_capture) pass the right
   ``?mode=series&shot=X&total=N`` for each state transition.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

# ``booth_main`` does ``import board`` at module top — stub before import.
sys.modules.setdefault("board", MagicMock())

from photobooth.booth_main import (  # noqa: E402 — post-stub import
    ATTRACT_URL,
    REVIEW_URL,
    SERIES_CAPTURE_URL,
    UNAVAILABLE_URL,
    PhotoBooth,
)


def _query(url: str) -> dict:
    """Return parsed query params with single-value lists collapsed."""
    parts = urlparse(url)
    raw = parse_qs(parts.query)
    return {k: v[0] if len(v) == 1 else v for k, v in raw.items()}


def _base(url: str) -> str:
    """Return the URL without its query string."""
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


@pytest.fixture
def booth():
    b = PhotoBooth()
    b.rpi = MagicMock()
    b.rpi.display_url = AsyncMock()
    b.rpi.copy_to_last_shot = MagicMock()
    b._flush_events = AsyncMock()
    b.panel = MagicMock()
    return b


# ---------------------------------------------------------------------------
# display_url_with_context helper
# ---------------------------------------------------------------------------


async def test_display_url_with_context_appends_query_string(booth):
    await booth.display_url_with_context(REVIEW_URL, mode="series", shot=2, total=3)
    args = booth.rpi.display_url.call_args.args
    assert _base(args[0]) == REVIEW_URL
    assert _query(args[0]) == {"mode": "series", "shot": "2", "total": "3"}


async def test_display_url_with_context_no_params_leaves_url_unchanged(booth):
    await booth.display_url_with_context(UNAVAILABLE_URL)
    booth.rpi.display_url.assert_awaited_once_with(UNAVAILABLE_URL)


# ---------------------------------------------------------------------------
# _series_params helper
# ---------------------------------------------------------------------------


def test_series_params_no_template_is_single_total_one(booth):
    # No ``self.strip`` attribute at all — getattr fallback kicks in.
    params = booth._series_params()
    assert params == {"mode": "single", "total": 1}


def test_series_params_single_shot_template_is_single(booth):
    booth.strip = MagicMock(shot_count=1)
    params = booth._series_params()
    assert params == {"mode": "single", "total": 1}


def test_series_params_multi_shot_template_is_series(booth):
    booth.strip = MagicMock(shot_count=4)
    params = booth._series_params()
    assert params == {"mode": "series", "total": 4}


def test_series_params_includes_shot_when_given(booth):
    booth.strip = MagicMock(shot_count=3)
    assert booth._series_params(shot=2) == {
        "mode": "series",
        "total": 3,
        "shot": 2,
    }


# ---------------------------------------------------------------------------
# _review_shot wires shot/total into the URL
# ---------------------------------------------------------------------------


async def test_review_shot_series_mode_appends_shot_and_total(booth):
    booth.strip = MagicMock(shot_count=3)
    booth.rpi.next_event = AsyncMock(return_value="green")

    await booth._review_shot("/tmp/shot.jpg", series_mode=True, shot=2, total=3)

    args = booth.rpi.display_url.call_args.args
    assert _base(args[0]) == REVIEW_URL
    assert _query(args[0]) == {"mode": "series", "shot": "2", "total": "3"}


async def test_review_shot_single_mode_forces_mode_single(booth):
    """Even with a multi-shot template active, ``series_mode=False``
    (single-shot review or in-series re-review) suppresses the banner
    by forcing ``mode=single``."""
    booth.strip = MagicMock(shot_count=3)
    booth.rpi.next_event = AsyncMock(return_value="green")

    await booth._review_shot("/tmp/shot.jpg", series_mode=False)

    args = booth.rpi.display_url.call_args.args
    assert _query(args[0])["mode"] == "single"
    # No banner means no ``shot`` param is needed.
    assert "shot" not in _query(args[0])


# ---------------------------------------------------------------------------
# _series_capture_review derives next_shot from len(shots)+1
# ---------------------------------------------------------------------------


async def test_series_capture_review_uses_next_shot_in_url(booth):
    booth.strip = MagicMock(shot_count=3)

    async def fake_scroll(*args, **kwargs):
        await asyncio.sleep(3600)

    booth.panel.scroll = fake_scroll

    # next_event returns "capture" → function returns "continue"
    # immediately after the first URL display, which is enough for the
    # URL assertion.
    booth.rpi.next_event = AsyncMock(return_value="capture")

    result = await booth._series_capture_review(
        ["shot1.jpg", "shot2.jpg"], last_decided="shot2.jpg"
    )
    assert result == "continue"

    args = booth.rpi.display_url.call_args.args
    assert _base(args[0]) == SERIES_CAPTURE_URL
    assert _query(args[0]) == {"mode": "series", "shot": "3", "total": "3"}


async def test_series_capture_review_first_shot_yet_to_be_taken(booth):
    """Camera-failure recovery path: ``last_decided=None``, shots empty
    after a redo cycle — the next shot is still 1 of N."""
    booth.strip = MagicMock(shot_count=2)

    async def fake_scroll(*args, **kwargs):
        await asyncio.sleep(3600)

    booth.panel.scroll = fake_scroll
    booth.rpi.next_event = AsyncMock(return_value="capture")

    await booth._series_capture_review([], last_decided=None)

    args = booth.rpi.display_url.call_args.args
    assert _query(args[0]) == {"mode": "series", "shot": "1", "total": "2"}
