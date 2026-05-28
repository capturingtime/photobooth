"""Tests for the ``BOOTH_*`` env-var → module-constant mapping in booth_main.

These constants are the entire surface for per-booth runtime configuration.
A rename or typo in either side (the env-var name in
``/etc/ctp/booth.env`` or the lookup in ``booth_main``) would silently fall
back to the hardcoded default, which is exactly the failure mode this test
suite exists to catch.

The booth's hardware deps (``board``, etc.) are stubbed via ``sys.modules`` so
``booth_main`` can be imported on a dev machine.
"""

import importlib
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _stub_board():
    """Stub ``board`` for the duration of the test session.

    ``photobooth.booth_main`` does ``import board`` at module top, which only
    resolves on a Raspberry Pi with Adafruit-Blinka installed. A MagicMock
    is sufficient — booth_main only references board's attributes inside
    functions that run on the live booth, never at import time.
    """
    sys.modules.setdefault("board", MagicMock())
    yield


def _reload_booth_main():
    """Force a clean re-evaluation of booth_main's module-top env-var reads."""
    if "photobooth.booth_main" in sys.modules:
        return importlib.reload(sys.modules["photobooth.booth_main"])
    import photobooth.booth_main as mod  # noqa: WPS433 — deliberate late import
    return mod


# ---------------------------------------------------------------------------
# Defaults: every env var unset → documented hardcoded fallback applies.
# ---------------------------------------------------------------------------


@pytest.fixture
def default_env(monkeypatch):
    for key in (
        "BOOTH_S3_BUCKET",
        "BOOTH_IMAGE_DIR",
        "BOOTH_CAMERA_MODEL",
        "BOOTH_MAX_PRINTS",
        "BOOTH_TEMPLATE_BASE_DIR",
        "BOOTH_ACTIVE_TEMPLATE",
    ):
        monkeypatch.delenv(key, raising=False)
    return _reload_booth_main()


def test_default_s3_bucket(default_env):
    assert default_env.S3_BUCKET == "public.capturingtimephoto.net"


def test_default_image_dir(default_env):
    assert default_env.BOOTH_DIR == "/opt/booth_images"


def test_default_camera_model(default_env):
    assert default_env.CAMERA_MODEL == "Canon EOS 800D"


def test_default_max_prints(default_env):
    assert default_env.MAX_PRINTS == 3
    assert isinstance(default_env.MAX_PRINTS, int)


def test_default_template_base_dir(default_env):
    assert default_env.TEMPLATE_BASE_DIR == "/opt/photobooth/templates"


def test_default_active_template(default_env):
    assert default_env.ACTIVE_TEMPLATE == "strip_test_template"


# ---------------------------------------------------------------------------
# Overrides: setting each env var flips the corresponding module constant.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env_key, const_name, env_value, expected",
    [
        ("BOOTH_S3_BUCKET", "S3_BUCKET", "other.example.com", "other.example.com"),
        ("BOOTH_IMAGE_DIR", "BOOTH_DIR", "/srv/booth", "/srv/booth"),
        ("BOOTH_CAMERA_MODEL", "CAMERA_MODEL", "Nikon Z6", "Nikon Z6"),
        ("BOOTH_MAX_PRINTS", "MAX_PRINTS", "7", 7),
        (
            "BOOTH_TEMPLATE_BASE_DIR",
            "TEMPLATE_BASE_DIR",
            "/srv/templates",
            "/srv/templates",
        ),
        ("BOOTH_ACTIVE_TEMPLATE", "ACTIVE_TEMPLATE", "custom_strip", "custom_strip"),
    ],
)
def test_env_override(monkeypatch, env_key, const_name, env_value, expected):
    monkeypatch.setenv(env_key, env_value)
    mod = _reload_booth_main()
    assert getattr(mod, const_name) == expected


def test_active_template_empty_string_becomes_none(monkeypatch):
    """Empty env value is documented to disable the compositor (single-shot mode)."""
    monkeypatch.setenv("BOOTH_ACTIVE_TEMPLATE", "")
    mod = _reload_booth_main()
    assert mod.ACTIVE_TEMPLATE is None
