"""Tests for the offline-tolerant post-capture upload flow (v0.5.0 Phase 6).

Two contracts pinned in this file:

1. ``_upload_or_enqueue`` returns ``(public_url(key), PENDING_UPLOAD_NOTICE)``
   when ``upload_with_timeout`` raises (TimeoutError or generic Exception)
   AND the item is added to the persistent queue. The QR remains valid
   because ``public_url`` is deterministic on the key.
2. ``_do_print`` embeds the pending notice on the receipt below the QR
   when the capture's upload was deferred.

Hardware/IO is stubbed identically to ``test_unavailable_mode.py`` —
``board`` is stubbed before booth_main import.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("board", MagicMock())

from photobooth import booth_main  # noqa: E402
from photobooth.booth_main import (  # noqa: E402
    PENDING_UPLOAD_NOTICE,
    UPLOADING_SCROLL_TEXT,
    PhotoBooth,
)
from photobooth.upload_queue import UploadQueue  # noqa: E402


@pytest.fixture
def booth(tmp_path, monkeypatch):
    """A ``PhotoBooth`` with hardware stubs and a tmp queue path."""
    queue_path = str(tmp_path / "upload_queue.json")
    monkeypatch.setattr(booth_main, "UPLOAD_QUEUE_PATH", queue_path)

    b = PhotoBooth()
    b.panel = MagicMock()
    b.panel.clear = MagicMock()
    # scroll runs forever until cancelled so we can observe the
    # "Uploading..." text on the call args.
    b.panel.scroll = AsyncMock(side_effect=lambda *a, **k: asyncio.sleep(3600))

    b._upload_queue = UploadQueue(queue_path)
    b._upload_queue_path = queue_path  # convenience for assertions
    return b


def _stub_uploader(booth, *, upload_side_effect=None):
    """Wire a minimal uploader with predictable make_key/public_url."""
    uploader = MagicMock()
    uploader.make_key = MagicMock(return_value="booth/2026/06/15/tok12345_shot.jpg")
    uploader.public_url = MagicMock(
        return_value="http://public.capturingtimephoto.net/booth/2026/06/15/tok12345_shot.jpg"
    )
    uploader.upload_with_timeout = AsyncMock(side_effect=upload_side_effect)
    booth.uploader = uploader
    return uploader


# ---------------------------------------------------------------------------
# _upload_or_enqueue
# ---------------------------------------------------------------------------


async def test_upload_success_returns_url_no_notice(booth):
    uploader = _stub_uploader(booth)
    uploader.upload_with_timeout = AsyncMock(return_value=None)
    qr_url, notice = await booth._upload_or_enqueue("/opt/booth_images/shot.jpg")

    assert qr_url == uploader.public_url.return_value
    assert notice is None
    # Queue stays empty on success.
    assert booth._upload_queue.list() == []
    # last_uploaded_path/key cached for reprint.
    assert booth._last_uploaded_path == "/opt/booth_images/shot.jpg"
    assert booth._last_uploaded_key == "booth/2026/06/15/tok12345_shot.jpg"


async def test_upload_timeout_enqueues_and_returns_public_url(booth):
    uploader = _stub_uploader(
        booth,
        upload_side_effect=asyncio.TimeoutError(),
    )
    qr_url, notice = await booth._upload_or_enqueue("/opt/booth_images/shot.jpg")

    # QR points at the predictable public URL — works once worker drains.
    assert qr_url == uploader.public_url.return_value
    assert notice == PENDING_UPLOAD_NOTICE

    items = booth._upload_queue.list()
    assert len(items) == 1
    assert items[0].key == "booth/2026/06/15/tok12345_shot.jpg"
    assert items[0].image_path == "/opt/booth_images/shot.jpg"


async def test_upload_generic_error_also_enqueues(booth):
    """A boto3 ConnectionError / ClientError / etc. is caught the same
    way as a timeout — the booth must not crash on any flavor of S3
    failure during capture.
    """
    uploader = _stub_uploader(
        booth,
        upload_side_effect=RuntimeError("EndpointConnectionError"),
    )
    qr_url, notice = await booth._upload_or_enqueue("/opt/booth_images/shot.jpg")

    assert qr_url == uploader.public_url.return_value
    assert notice == PENDING_UPLOAD_NOTICE
    assert len(booth._upload_queue.list()) == 1


async def test_uploading_scroll_runs_during_attempt(booth):
    uploader = _stub_uploader(booth)
    uploader.upload_with_timeout = AsyncMock(return_value=None)
    await booth._upload_or_enqueue("/opt/booth_images/shot.jpg")

    # The scroll task was launched with the "Uploading..." text and
    # ``count=999`` — i.e. continuous until cancelled in ``finally``.
    assert booth.panel.scroll.call_args is not None
    kwargs = booth.panel.scroll.call_args.kwargs
    assert kwargs["text"] == UPLOADING_SCROLL_TEXT
    assert kwargs["count"] == 999
    # And the panel was cleared once the scroll was cancelled.
    booth.panel.clear.assert_called_once()


async def test_no_uploader_returns_none_pair(booth):
    booth.uploader = None
    qr_url, notice = await booth._upload_or_enqueue("/opt/booth_images/shot.jpg")
    assert qr_url is None
    assert notice is None
    # Scroll never started — no uploader, no work to do.
    booth.panel.scroll.assert_not_called()


# ---------------------------------------------------------------------------
# _do_print embeds pending_notice
# ---------------------------------------------------------------------------


def test_do_print_includes_pending_notice_when_present(booth):
    booth.printer = MagicMock()
    booth._do_print(
        "http://public.capturingtimephoto.net/booth/k", pending_notice=PENDING_UPLOAD_NOTICE
    )

    text_args = [c.args[0] for c in booth.printer.text.call_args_list]
    assert PENDING_UPLOAD_NOTICE in text_args


def test_do_print_omits_notice_when_none(booth):
    booth.printer = MagicMock()
    booth._do_print("http://public.capturingtimephoto.net/booth/k", pending_notice=None)

    text_args = [c.args[0] for c in booth.printer.text.call_args_list]
    assert PENDING_UPLOAD_NOTICE not in text_args
