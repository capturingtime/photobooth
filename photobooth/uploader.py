import asyncio
import functools
import logging
import secrets
from datetime import datetime
from typing import Optional

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

PRESIGN_EXPIRY_SECONDS: int = 604800  # 7 days


class Uploader:
    """Uploads captured images to S3 and returns presigned download URLs.

    boto3 is synchronous; all network I/O is offloaded to the default thread
    executor via run_in_executor so the asyncio event loop is never blocked.

    Usage:
        uploader = Uploader(bucket_name="public.capturingtimephoto.net")
        url = await uploader.upload("/opt/captures/20240101-12h00m00s.jpg")
        # url is a 7-day presigned GET link suitable for printing as a QR code
    """

    def __init__(self, bucket_name: str, bucket_role: str = "standard"):
        # Import here so the module can be imported on non-Pi hardware without
        # triggering boto3 connection attempts at import time.
        from utilities.clients.aws.client import AWS

        self._bucket_name = bucket_name
        self._aws = AWS()
        self._bucket = self._aws.load_bucket(bucket_name, bucket_role=bucket_role)

        # Determine bucket region so presigned URLs are signed for the correct endpoint.
        # Bucket names with dots also require path-style addressing to avoid SSL wildcard
        # cert mismatch (*.s3.amazonaws.com doesn't cover sub-dotted names).
        _probe = boto3.client("s3")
        region = (
            _probe.get_bucket_location(Bucket=bucket_name).get("LocationConstraint")
            or "us-east-1"
        )
        self._s3_client = boto3.client(
            "s3",
            region_name=region,
            config=Config(s3={"addressing_style": "path"}),
        )

    @staticmethod
    def make_key(image_path: str, prefix: str = "booth") -> str:
        """Build an S3 key from the local image path.

        Format: <prefix>/<YYYY>/<MM>/<DD>/<token>_<filename>
        Example: booth/2024/09/15/aB3xK9p2_20240915-12h30m00s-000001.jpg

        The token is the access control mechanism for public buckets — keys
        are unguessable, so the URL itself is the capability. Callers that
        need a stable key across reprints must stash the value returned here.
        """
        filename = image_path.rsplit("/", 1)[-1]
        now = datetime.now()
        token = secrets.token_urlsafe(8)
        return f"{prefix}/{now.strftime('%Y/%m/%d')}/{token}_{filename}"

    def public_url(self, key: str) -> str:
        """Build the customer-facing download URL for an uploaded object.

        Assumes the bucket name is a public-read CNAME (the bucket name is
        also the hostname, e.g. ``public.capturingtimephoto.net``). HTTP only;
        HTTPS to a dotted S3 bucket name needs CloudFront in front because
        S3's wildcard cert doesn't cover dotted hostnames.
        """
        return f"http://{self._bucket_name}/{key}"

    async def upload_with_timeout(
        self,
        image_path: str,
        key: Optional[str] = None,
        timeout_s: float = 5.0,
    ) -> str:
        """Upload with a hard wall-clock timeout.

        Wraps ``upload`` in ``asyncio.wait_for`` so the booth never blocks
        the capture flow for more than ``timeout_s`` on a slow/dead link.
        On timeout, ``asyncio.TimeoutError`` propagates; the caller's
        offline path (Phase 6) catches it and enqueues for later.

        The underlying executor task is cancelled by ``wait_for`` — boto3
        itself ignores the cancellation (it's running in a thread), but
        the foreground awaitable returns immediately so the capture flow
        proceeds without waiting on the executor.
        """
        return await asyncio.wait_for(
            self.upload(image_path, key=key),
            timeout=timeout_s,
        )

    async def upload(self, image_path: str, key: Optional[str] = None) -> str:
        """Upload a local file to S3 and return a presigned download URL.

        Args:
            image_path: Absolute path to the local image file.
            key: S3 object key. Defaults to make_key(image_path).

        Returns:
            A presigned HTTPS URL valid for PRESIGN_EXPIRY_SECONDS seconds.
        """
        if key is None:
            key = self.make_key(image_path)

        # Import inside method so the ctp-utilities package is not required
        # at module import time (useful for tests that mock the uploader).
        from utilities.classes.path.file import File

        logger.info(
            "S3 upload starting: bucket=%s key=%s file=%s",
            self._bucket_name,
            key,
            image_path,
        )
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                self._bucket.put_item,
                key,
                File(image_path),
            )
        except Exception as exc:
            logger.error(
                "S3 upload failed: bucket=%s key=%s — %s",
                self._bucket_name,
                key,
                exc,
            )
            raise
        logger.info("S3 upload complete: key=%s", key)
        return self.public_url(key)

    async def presign(self, key: str, expires: int = PRESIGN_EXPIRY_SECONDS) -> str:
        """Generate a presigned GET URL for an existing S3 object.

        Args:
            key: S3 object key.
            expires: URL validity in seconds (default 7 days).

        Returns:
            A presigned HTTPS URL.
        """
        loop = asyncio.get_running_loop()
        url = await loop.run_in_executor(
            None,
            functools.partial(
                self._s3_client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self._bucket_name, "Key": key},
                ExpiresIn=expires,
            ),
        )
        logger.debug("S3 presign: key=%s expires=%ds", key, expires)
        return url
