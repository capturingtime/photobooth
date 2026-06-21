"""Tests for photobooth.logging_config.setup_logging()."""

import logging
import logging.handlers

import pytest

from photobooth import logging_config
from photobooth.logging_config import setup_logging


@pytest.fixture(autouse=True)
def _reset_photobooth_logger(monkeypatch, tmp_path):
    """Wipe handler/level state on the ``photobooth`` logger before each test.

    ``setup_logging()`` is idempotent via a sentinel attribute, so leaving
    state between tests would mean only the first test ever observed a fresh
    setup. Also redirect the file handler away from ``/var/log/`` so the test
    suite can actually write it.
    """
    root = logging.getLogger("photobooth")
    for h in list(root.handlers):
        root.removeHandler(h)
    if hasattr(root, "_photobooth_configured"):
        delattr(root, "_photobooth_configured")
    root.setLevel(logging.NOTSET)

    monkeypatch.setattr(logging_config, "LOG_FILE", str(tmp_path / "photobooth.log"))
    monkeypatch.delenv("BOOTH_LOG_LEVEL", raising=False)
    yield


def _handlers_by_type(logger):
    out = {}
    for h in logger.handlers:
        out.setdefault(type(h).__name__, []).append(h)
    return out


def test_default_level_is_info():
    setup_logging()
    assert logging.getLogger("photobooth").level == logging.INFO


def test_explicit_debug_level(monkeypatch):
    monkeypatch.setenv("BOOTH_LOG_LEVEL", "DEBUG")
    setup_logging()
    assert logging.getLogger("photobooth").level == logging.DEBUG


def test_level_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("BOOTH_LOG_LEVEL", "warning")
    setup_logging()
    assert logging.getLogger("photobooth").level == logging.WARNING


def test_bad_level_falls_back_to_info_and_warns(monkeypatch, caplog):
    monkeypatch.setenv("BOOTH_LOG_LEVEL", "BOGUS")
    caplog.set_level("WARNING", logger="photobooth")

    setup_logging()

    root = logging.getLogger("photobooth")
    assert root.level == logging.INFO
    warnings = [
        r
        for r in caplog.records
        if "BOOTH_LOG_LEVEL" in r.getMessage() or (r.args and "BOGUS" in str(r.args))
    ]
    assert warnings, "expected a WARNING about the bad BOOTH_LOG_LEVEL value"


def test_is_idempotent():
    setup_logging()
    setup_logging()
    setup_logging()

    handlers = _handlers_by_type(logging.getLogger("photobooth"))
    assert len(handlers.get("RotatingFileHandler", [])) == 1
    assert len(handlers.get("StreamHandler", [])) == 1


def test_file_handler_attached_at_debug():
    setup_logging()
    file_handlers = [
        h
        for h in logging.getLogger("photobooth").handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].level == logging.DEBUG


def test_stderr_handler_attached_at_warning():
    setup_logging()
    stream_handlers = [
        h for h in logging.getLogger("photobooth").handlers if type(h) is logging.StreamHandler
    ]
    assert len(stream_handlers) == 1
    assert stream_handlers[0].level == logging.WARNING


def test_unwritable_log_file_does_not_raise(monkeypatch):
    """If ``/var/log`` is not writable (e.g. on a dev box) the stderr handler
    must still attach and ``setup_logging()`` must return normally — losing
    the file handler is not a hard failure."""
    monkeypatch.setattr(logging_config, "LOG_FILE", "/proc/definitely/not/writable.log")

    setup_logging()

    handlers = logging.getLogger("photobooth").handlers
    assert any(type(h) is logging.StreamHandler for h in handlers)
    assert not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)
