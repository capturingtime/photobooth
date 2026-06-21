"""Tests for photobooth.uploader.

Coverage focus: regression protection for the two v0.4.0 fixes in this module.

1. ``make_key()`` must return a *different* token on every call. The reprint
   bug came from the prior callsite re-invoking ``make_key()`` and getting a
   fresh random token each time, so the reprint QR pointed at an object that
   never existed in S3.
2. ``public_url()`` must return a plain ``http://<bucket>/<key>`` URL with no
   AWS-credential query parameters. The earlier ``upload()`` returned a
   presigned URL containing ``AWSAccessKeyId`` / ``X-Amz-Signature``, which
   then landed in log files and on printed receipts.
"""

import re
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("utilities", reason="ctp-utilities not installed")
pytest.importorskip("boto3")


KEY_PATTERN = re.compile(r"^[\w-]+/\d{4}/\d{2}/\d{2}/[A-Za-z0-9_-]{8,}_.+$")


@pytest.fixture
def uploader():
    """An ``Uploader`` with every external call mocked.

    boto3's ``get_bucket_location`` and ``client(...)`` constructors are
    replaced with no-op mocks so ``Uploader.__init__`` can run without AWS
    credentials, network, or the ctp-utilities ``AWS`` client doing real work.
    """
    fake_aws = MagicMock()
    fake_bucket = MagicMock()
    fake_aws.load_bucket.return_value = fake_bucket

    fake_probe = MagicMock()
    fake_probe.get_bucket_location.return_value = {"LocationConstraint": "us-west-2"}
    fake_s3_client = MagicMock()

    with patch("utilities.clients.aws.client.AWS", return_value=fake_aws), patch(
        "photobooth.uploader.boto3.client", side_effect=[fake_probe, fake_s3_client]
    ):
        from photobooth.uploader import Uploader

        u = Uploader(bucket_name="test.bucket.example.com")

    u._fake_bucket = fake_bucket
    u._fake_s3_client = fake_s3_client
    return u


class TestMakeKey:
    def test_format_matches_documented_shape(self):
        from photobooth.uploader import Uploader

        key = Uploader.make_key("/tmp/20240915-12h30m00s-000001.jpg")
        assert KEY_PATTERN.match(key), f"key {key!r} does not match expected shape"

    def test_default_prefix_is_booth(self):
        from photobooth.uploader import Uploader

        key = Uploader.make_key("/tmp/foo.jpg")
        assert key.startswith("booth/")

    def test_custom_prefix_is_respected(self):
        from photobooth.uploader import Uploader

        key = Uploader.make_key("/tmp/foo.jpg", prefix="archive")
        assert key.startswith("archive/")

    def test_filename_is_preserved(self):
        from photobooth.uploader import Uploader

        key = Uploader.make_key("/some/nested/path/IMG_4242.jpg")
        assert key.endswith("_IMG_4242.jpg")

    def test_tokens_are_unique_across_calls(self):
        """Regression: the reprint bug was a different token per call.

        That's now the desired behaviour for *new* uploads, but it's the reason
        callers must stash the key — verify the property explicitly so a future
        refactor doesn't accidentally make make_key deterministic and silently
        re-break the reprint contract.
        """
        from photobooth.uploader import Uploader

        keys = {Uploader.make_key("/tmp/foo.jpg") for _ in range(200)}
        assert len(keys) == 200


class TestPublicUrl:
    def test_returns_plain_cname_url(self, uploader):
        url = uploader.public_url("booth/2026/05/20/abc12345_shot.jpg")
        assert url == "http://test.bucket.example.com/booth/2026/05/20/abc12345_shot.jpg"

    def test_contains_no_credentials(self, uploader):
        url = uploader.public_url("booth/2026/05/20/abc12345_shot.jpg")
        forbidden = (
            "AKIA",
            "X-Amz-Signature",
            "Signature=",
            "X-Amz-Credential",
            "X-Amz-SecurityToken",
            "AWSAccessKeyId",
            "?",
        )
        for needle in forbidden:
            assert needle not in url, f"{needle!r} unexpectedly present in {url!r}"


class TestPredictableUrlContract:
    """v0.5.0 Phase 6 documents the deterministic-by-key contract.

    The offline-upload flow leans on ``public_url(key)`` returning the
    same string for the same ``key`` every time — that's the property
    that lets the printed QR keep working after the upload eventually
    drains from the queue.
    """

    def test_public_url_is_deterministic_for_a_given_key(self, uploader):
        key = "booth/2026/05/20/abc12345_shot.jpg"
        # Same key -> same URL across calls (no signature, no expiry).
        urls = {uploader.public_url(key) for _ in range(20)}
        assert len(urls) == 1

    def test_public_url_matches_make_key_output_shape(self, uploader):
        """The QR printed on the receipt is built from ``public_url(key)``;
        verify ``make_key`` output flows through ``public_url`` without
        any mangling that would break the round-trip.
        """
        from photobooth.uploader import Uploader

        key = Uploader.make_key("/tmp/shot.jpg")
        url = uploader.public_url(key)
        assert url == f"http://test.bucket.example.com/{key}"


class TestUploadWithTimeout:
    """``upload_with_timeout`` wraps ``upload`` in ``asyncio.wait_for``
    so the capture flow can move on if the link is dead. The wrapper
    must surface ``TimeoutError`` cleanly and propagate non-timeout
    errors unchanged so the caller can distinguish offline from
    misconfiguration.
    """

    async def test_timeout_raises_asyncio_timeout_error(self, uploader, tmp_path):
        import asyncio

        async def slow_upload(*a, **k):
            await asyncio.sleep(5)
            return "url"

        uploader.upload = slow_upload  # type: ignore[method-assign]
        with pytest.raises(asyncio.TimeoutError):
            await uploader.upload_with_timeout(str(tmp_path / "shot.jpg"), key="k", timeout_s=0.05)

    async def test_success_returns_public_url(self, uploader, tmp_path):
        from unittest.mock import patch

        with patch("utilities.classes.path.file.File"):
            url = await uploader.upload_with_timeout(
                str(tmp_path / "shot.jpg"),
                key="booth/2026/05/20/abc12345_shot.jpg",
                timeout_s=5.0,
            )
        assert url == "http://test.bucket.example.com/booth/2026/05/20/abc12345_shot.jpg"


class TestUpload:
    async def test_returns_public_url_not_presigned(self, uploader, tmp_path):
        with patch("utilities.classes.path.file.File"):
            url = await uploader.upload(str(tmp_path / "shot.jpg"))

        assert url.startswith("http://test.bucket.example.com/booth/")
        assert "Signature" not in url and "AKIA" not in url
        uploader._fake_s3_client.generate_presigned_url.assert_not_called()

    async def test_uses_provided_key_when_supplied(self, uploader, tmp_path):
        fixed_key = "booth/2026/05/20/fixed12_shot.jpg"
        with patch("utilities.classes.path.file.File"):
            url = await uploader.upload(str(tmp_path / "shot.jpg"), key=fixed_key)

        assert url == f"http://test.bucket.example.com/{fixed_key}"

    async def test_failure_reraises_after_logging(self, uploader, tmp_path, caplog):
        uploader._fake_bucket.put_item.side_effect = RuntimeError("boom")
        with patch("utilities.classes.path.file.File"), pytest.raises(RuntimeError):
            await uploader.upload(str(tmp_path / "shot.jpg"))

        # Error was logged before the re-raise.
        assert any("upload failed" in r.message.lower() for r in caplog.records)
