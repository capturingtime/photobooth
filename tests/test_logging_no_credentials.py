"""Regression test for the v0.4.0 credential-leak fix.

The earlier code returned a presigned S3 URL from ``Uploader.upload()`` and
then logged it as ``"S3 upload complete: ... url=%s"`` and
``"Printing receipt: url=%s"``. Those URLs carry ``AWSAccessKeyId`` and
``X-Amz-Signature`` query parameters — i.e. AWS credential material — and
landed in plaintext in ``/var/log/photobooth.log``.

This test exercises the upload + presign paths and asserts that no log record
emitted along the way contains any known AWS credential-substring pattern.
A regression here is a production-grade security incident; the test should
remain even if the implementation is rewritten.
"""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("utilities", reason="ctp-utilities not installed")
pytest.importorskip("boto3")


# Substrings that should NEVER appear in any photobooth log line. Drawn from
# the AWS SigV2 and SigV4 query-parameter names, plus the access-key-id prefix.
CREDENTIAL_PATTERNS = (
    "AKIA",  # Access key ID prefix (SigV2 and long-term SigV4 keys)
    "ASIA",  # Temporary STS access key ID prefix
    "X-Amz-Signature",
    "X-Amz-Credential",
    "X-Amz-SecurityToken",
    "Signature=",
    "AWSAccessKeyId",
)


def _record_strings(record):
    """Materialize every string a logging.LogRecord can carry.

    A naive ``record.message`` check misses values passed through ``%s`` /
    ``%r`` formatting (``logger.info("url=%s", url)`` keeps ``url`` in
    ``record.args``, not in ``record.message`` until ``getMessage()`` runs).
    Check both the rendered message and the raw arg tuple.
    """
    yield record.getMessage()
    args = record.args
    if args is None:
        return
    if isinstance(args, dict):
        for v in args.values():
            yield str(v)
    elif isinstance(args, tuple):
        for v in args:
            yield str(v)
    else:
        yield str(args)


def assert_no_credentials(records):
    for r in records:
        for s in _record_strings(r):
            for needle in CREDENTIAL_PATTERNS:
                assert needle not in s, (
                    f"credential pattern {needle!r} leaked into log record "
                    f"from {r.name} at {r.levelname}: {s!r}"
                )


@pytest.fixture
def uploader(caplog):
    caplog.set_level("DEBUG", logger="photobooth")

    fake_aws = MagicMock()
    fake_bucket = MagicMock()
    fake_aws.load_bucket.return_value = fake_bucket

    fake_probe = MagicMock()
    fake_probe.get_bucket_location.return_value = {"LocationConstraint": "us-west-2"}
    fake_s3_client = MagicMock()
    # If anyone calls presign, return a string that LOOKS like a real presigned
    # URL — that way if it ends up in a log line we'll catch it.
    fake_s3_client.generate_presigned_url.return_value = (
        "https://test.bucket.example.com/booth/k.jpg"
        "?AWSAccessKeyId=AKIAIOSFODNN7EXAMPLE"
        "&Signature=tHeSiGnAtUrEbAsE64%3D"
        "&Expires=1700000000"
    )

    with patch("utilities.clients.aws.client.AWS", return_value=fake_aws), patch(
        "photobooth.uploader.boto3.client", side_effect=[fake_probe, fake_s3_client]
    ):
        from photobooth.uploader import Uploader

        u = Uploader(bucket_name="test.bucket.example.com")

    u._fake_bucket = fake_bucket
    u._fake_s3_client = fake_s3_client
    return u


async def test_upload_success_logs_contain_no_credentials(uploader, tmp_path, caplog):
    with patch("utilities.classes.path.file.File"):
        url = await uploader.upload(str(tmp_path / "shot.jpg"))

    # The returned URL is the public CNAME form — also credential-free.
    assert "AKIA" not in url and "Signature" not in url
    assert_no_credentials(caplog.records)


async def test_upload_failure_logs_contain_no_credentials(uploader, tmp_path, caplog):
    uploader._fake_bucket.put_item.side_effect = RuntimeError("boom")

    with patch("utilities.classes.path.file.File"), pytest.raises(RuntimeError):
        await uploader.upload(str(tmp_path / "shot.jpg"))

    assert_no_credentials(caplog.records)


async def test_presign_url_value_is_not_logged(uploader, caplog):
    """``presign()`` is retained for future private-bucket use.

    Even when it's exercised, the URL string it returns must not appear in
    any log record — only the key.
    """
    url = await uploader.presign("booth/2026/05/20/abc12345_shot.jpg")

    # Sanity: our fake URL really does contain the markers we're scanning for.
    assert "AKIA" in url and "Signature=" in url

    assert_no_credentials(caplog.records)
