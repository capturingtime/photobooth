"""Tests for photobooth.camera.

Coverage focus: the v0.4.0 logging conversion (the `print(err)` in
``run_local_cmd`` became ``logger.error``) and the small pure helpers around
gphoto2. The hardware-touching paths (full ``Camera`` init, ``capture_async``
against a real camera) are not covered — those are exercised by the live
booth smoke test in BACKLOG.md.
"""

import subprocess
from unittest.mock import patch

import pytest

from photobooth import camera


class TestRunLocalCmd:
    def test_success_returns_completedprocess(self):
        result = camera.run_local_cmd("echo hello")
        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == 0
        assert b"hello" in result.stdout

    def test_exception_is_logged_at_error_not_raised(self, caplog):
        """The v0.4.0 conversion: ``print(err)`` → ``logger.error(...)``.

        Even if subprocess.run raises (the bare ``except Exception`` catches
        everything), ``run_local_cmd`` must return None and emit one ERROR
        log record. A regression here means subprocess crashes blow up the
        booth instead of being captured for forensics.
        """
        caplog.set_level("ERROR", logger="photobooth.camera")
        with patch.object(camera.subprocess, "run", side_effect=OSError("boom")):
            result = camera.run_local_cmd("anything")
        assert result is None
        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert errors, "expected an ERROR log record from run_local_cmd"
        assert "run_local_cmd failed" in errors[0].getMessage()


class TestBuildFilename:
    def test_filename_includes_download_dir(self):
        out = camera._build_filename("/tmp/x")
        assert out.startswith("/tmp/x/")

    def test_filename_has_jpg_extension(self):
        out = camera._build_filename("/tmp/x")
        assert out.endswith(".jpg")

    def test_filename_pattern_matches_timestamp(self):
        import re

        out = camera._build_filename("/tmp/x")
        # YYYYMMDD-HHhMMmSSs-microseconds.jpg
        assert re.match(
            r"/tmp/x/\d{8}-\d{2}h\d{2}m\d{2}s-\d{6}\.jpg$", out
        ), f"unexpected filename shape: {out}"


class TestCheckGphoto2:
    def test_returns_true_when_gphoto2_present(self):
        fake = subprocess.CompletedProcess(
            args="which gphoto2", returncode=0, stdout=b"/usr/bin/gphoto2\n", stderr=b""
        )
        with patch.object(camera.subprocess, "run", return_value=fake):
            assert camera.check_gphoto2() is True

    def test_raises_when_gphoto2_missing(self):
        fake = subprocess.CompletedProcess(
            args="which gphoto2", returncode=1, stdout=b"\n", stderr=b""
        )
        with patch.object(camera.subprocess, "run", return_value=fake):
            with pytest.raises(RuntimeError, match="GPhoto2 was not found"):
                camera.check_gphoto2()


class TestReadExifDatetime:
    """The helper underpins the spurious-capture forensic log line; it must
    never raise, regardless of input. A None return is the documented
    "no usable EXIF" signal — never a crash."""

    def test_returns_none_for_missing_file(self):
        assert camera._read_exif_datetime("/no/such/path.jpg") is None

    def test_returns_none_for_non_image_file(self, tmp_path):
        p = tmp_path / "not_an_image.txt"
        p.write_text("definitely not a jpeg")
        assert camera._read_exif_datetime(str(p)) is None

    def test_returns_none_for_image_without_exif(self, tmp_path):
        from PIL import Image

        p = tmp_path / "no_exif.jpg"
        Image.new("RGB", (10, 10), color=(128, 128, 128)).save(p, "JPEG")
        # A freshly created PIL JPEG has no EXIF block.
        assert camera._read_exif_datetime(str(p)) is None


class TestCheckDirRwOrMake:
    def test_creates_directory_when_missing(self, tmp_path):
        target = tmp_path / "newdir"
        assert not target.exists()
        assert camera.check_dir_rw_or_make(str(target)) is True
        assert target.is_dir()

    def test_returns_true_when_directory_exists_and_writable(self, tmp_path):
        assert camera.check_dir_rw_or_make(str(tmp_path)) is True
