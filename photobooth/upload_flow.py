"""Offline-tolerant S3 upload subsystem (Phase 6).

``UploadFlowMixin`` carries the two cooperating halves of the upload path:

* ``_upload_or_enqueue`` — the capture-time attempt with a wall-clock cap,
  falling back to the persistent queue when S3 is slow or unreachable.
* ``_upload_queue_worker`` — the lifetime background task that drains the
  queue once connectivity recovers.

``PhotoBooth`` inherits the mixin, so both run as ordinary instance methods
against ``self`` (``self.uploader`` / ``self._upload_queue`` / ``self.health``
/ ``self.panel``), which ``PhotoBooth._startup`` and ``run`` own.
"""

import asyncio
import logging

from photobooth.config import (
    PENDING_UPLOAD_NOTICE,
    S3_BUCKET,
    UPLOAD_TIMEOUT_SECONDS,
    UPLOAD_WORKER_BACKOFF_CAP,
    UPLOAD_WORKER_BACKOFF_INITIAL,
    UPLOADING_SCROLL_TEXT,
)

logger = logging.getLogger(__name__)


class UploadFlowMixin:
    """Upload-path methods mixed into ``PhotoBooth``."""

    async def _upload_or_enqueue(self, image_path: str) -> tuple:
        """Attempt S3 upload with a 5s wall-clock cap; queue on failure.

        Returns ``(qr_url, pending_notice)``:

        * ``qr_url`` — the deterministic ``public_url(key)``. Used as the
          QR target on the receipt regardless of whether the upload
          actually completed; if it didn't, the queue worker eventually
          puts the object at that key.
        * ``pending_notice`` — None on success, a short string on
          failure that gets embedded under the QR on the receipt so the
          user knows to scan again after the booth reconnects.

        ``None, None`` is returned when no uploader was configured (dev
        environment). Caller treats ``qr_url is None`` as "no receipt".

        The "Uploading..." scroll runs as a background task on the
        neopixel for the whole window and is cancelled in ``finally``
        regardless of outcome. ``self._last_uploaded_path`` / ``_key``
        are populated up front so the reprint path can target the same
        S3 object whether the upload landed now or via the queue worker.
        """
        if self.uploader is None:
            return (None, None)

        key = self.uploader.make_key(image_path)
        qr_url = self.uploader.public_url(key)
        self._last_uploaded_path = image_path
        self._last_uploaded_key = key

        # Short-circuit when HealthMonitor already knows the network is
        # down. boto3's blocking executor call can wedge well past the
        # asyncio.wait_for timeout when DNS itself is unreachable, which
        # was causing the post-capture flow (receipt print + green-button
        # consumption) to stall indefinitely on a fully-offline booth.
        # The queue worker re-attempts once net_www flips back to ready.
        health = getattr(self, "health", None)
        net_ready = True if health is None else health.is_ready("net_www")
        if not net_ready:
            logger.info(
                "Network offline (net_www unavailable) — enqueueing key=%s without upload attempt",
                key,
            )
            self._upload_queue.enqueue(key, image_path)
            return (qr_url, PENDING_UPLOAD_NOTICE)

        logger.info("Uploading: file=%s bucket=%s", image_path, S3_BUCKET)
        scroll_task = asyncio.create_task(
            self.panel.scroll(
                text=UPLOADING_SCROLL_TEXT,
                speed=0.005,
                count=999,
            )
        )
        pending_notice = None

        async def _queue_for_retry() -> None:
            # Shared failure tail for both the timeout and the generic
            # boto3-error arms: queue the capture under the deterministic
            # key, then force a net_www recheck so the queue worker waits
            # for recovery instead of pounding on a known-bad link.
            self._upload_queue.enqueue(key, image_path)
            if health is not None:
                try:
                    await health._probe_once("net_www")
                except Exception as probe_exc:
                    logger.debug("net_www probe after upload failure: %s", probe_exc)

        try:
            try:
                await self.uploader.upload_with_timeout(
                    image_path,
                    key=key,
                    timeout_s=UPLOAD_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Upload timed out after %.1fs — enqueueing key=%s",
                    UPLOAD_TIMEOUT_SECONDS,
                    key,
                )
                await _queue_for_retry()
                pending_notice = PENDING_UPLOAD_NOTICE
            except Exception as exc:
                # boto3 client/connection errors land here; any of them
                # signal "S3 isn't usable right now" — queue and move on.
                logger.warning("Upload failed (%s) — enqueueing key=%s", exc, key)
                await _queue_for_retry()
                pending_notice = PENDING_UPLOAD_NOTICE
        finally:
            scroll_task.cancel()
            try:
                await scroll_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("Upload scroll exit error: %s", exc)
            self.panel.clear()
        return (qr_url, pending_notice)

    async def _upload_queue_worker(self) -> None:
        """Drain the upload queue while ``HealthMonitor`` reports net_www ready.

        Idle path: peek at queue head; if internet is healthy, attempt
        the upload; on success ``pop``, on failure ``mark_attempt`` and
        push net_www to ``unavailable`` (so the recheck loop is the one
        flipping it back to ``ready`` once connectivity recovers).

        Backoff: ``UPLOAD_WORKER_BACKOFF_INITIAL`` doubles after each
        consecutive failure, capped at ``UPLOAD_WORKER_BACKOFF_CAP``.
        A successful drain resets the backoff so the next outage starts
        fresh from the short interval.

        Cancellable: the task is created in ``_startup`` and stays alive
        for the booth's lifetime. ``asyncio.CancelledError`` propagates
        cleanly so a clean shutdown doesn't leave a half-uploaded item.
        """
        logger.info("Upload queue worker started")
        backoff = UPLOAD_WORKER_BACKOFF_INITIAL
        try:
            while True:
                item = self._upload_queue.peek()
                if item is None:
                    # Queue empty — short sleep so a freshly enqueued
                    # item drains promptly without busy-waiting.
                    await asyncio.sleep(UPLOAD_WORKER_BACKOFF_INITIAL)
                    backoff = UPLOAD_WORKER_BACKOFF_INITIAL
                    continue

                if self.uploader is None:
                    await asyncio.sleep(UPLOAD_WORKER_BACKOFF_CAP)
                    continue

                # Only attempt when the health monitor says net_www is
                # ready; otherwise back off and let recheck_loop do its
                # job. The booth is not a connectivity probe — this loop
                # is for upload work.
                try:
                    net_ready = self.health.is_ready("net_www")
                except KeyError:
                    net_ready = False
                if not net_ready:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, UPLOAD_WORKER_BACKOFF_CAP)
                    continue

                try:
                    await self.uploader.upload(item.image_path, key=item.key)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Queued upload failed: key=%s attempts=%d err=%s",
                        item.key,
                        item.attempts + 1,
                        exc,
                    )
                    self._upload_queue.mark_attempt(item.key, repr(exc))
                    # Push net_www to unavailable so ``recheck_loop`` polls
                    # it back to ready when the link returns.
                    try:
                        await self.health._probe_once("net_www")
                    except Exception as probe_exc:  # noqa: BLE001 — probe rules guarantee no raise
                        logger.debug("net_www probe after upload fail: %s", probe_exc)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, UPLOAD_WORKER_BACKOFF_CAP)
                    continue

                # Success: drop the item and reset backoff so the next
                # outage gets the fast initial retry interval again.
                self._upload_queue.pop(item.key)
                logger.info("Queued upload completed: key=%s", item.key)
                backoff = UPLOAD_WORKER_BACKOFF_INITIAL
        except asyncio.CancelledError:
            logger.info("Upload queue worker cancelled")
            raise
