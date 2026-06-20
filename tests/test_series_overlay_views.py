"""Tests for the v0.5.0 Phase 7 series-banner overlay views.

The Django views ``attract``, ``last_capture``, and ``series_capture``
each accept ``?mode=&total=&shot=`` query params and pass them as
template context. The templates conditionally render a centered
``.series-banner`` div positioned over the static frame artwork:

* ``attract.html``      — banner only when ``mode == "series"``.
* ``last_capture.html`` — banner only when ``mode == "series"``.
* ``series_capture.html`` — banner always present (the page is only
  rendered between shots of a series).

These tests exercise the Django test client against the in-process
template + URL stack, asserting the right banner text appears (or is
absent) for representative query-string combinations.
"""

import os
import sys
from pathlib import Path

import django
from django.test import Client

# Make the Django project importable. The runtime ``photobooth-run``
# entry point spawns the Django server via ``rpi.start_web``, but for
# tests we bring up the URL config in-process by pointing
# ``DJANGO_SETTINGS_MODULE`` at the project's settings before calling
# ``django.setup()``.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DJANGO_PROJECT_ROOT = PROJECT_ROOT / "photobooth_web"
sys.path.insert(0, str(DJANGO_PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "photobooth_web.settings")
django.setup()


def _decode(response) -> str:
    return response.content.decode("utf-8")


# ---------------------------------------------------------------------------
# attract.html
# ---------------------------------------------------------------------------


def test_attract_no_params_omits_banner():
    client = Client()
    body = _decode(client.get("/main/attract/"))
    assert 'class="series-banner"' not in body


def test_attract_single_mode_omits_banner():
    client = Client()
    body = _decode(client.get("/main/attract/?mode=single&total=1"))
    assert 'class="series-banner"' not in body


def test_attract_series_mode_renders_banner():
    client = Client()
    body = _decode(client.get("/main/attract/?mode=series&total=3"))
    assert 'class="series-banner"' in body
    assert "3 photos will be taken for the series" in body


# ---------------------------------------------------------------------------
# last_capture.html
# ---------------------------------------------------------------------------


def test_last_capture_no_params_omits_banner():
    client = Client()
    body = _decode(client.get("/main/last_capture/"))
    assert 'class="series-banner"' not in body


def test_last_capture_single_mode_omits_banner():
    client = Client()
    body = _decode(client.get("/main/last_capture/?mode=single&total=1&shot=1"))
    assert 'class="series-banner"' not in body


def test_last_capture_series_mode_renders_shot_of_total():
    client = Client()
    body = _decode(client.get("/main/last_capture/?mode=series&shot=2&total=3"))
    assert 'class="series-banner"' in body
    assert "Shot 2 of 3" in body


# ---------------------------------------------------------------------------
# series_capture.html
# ---------------------------------------------------------------------------


def test_series_capture_renders_next_shot_banner():
    client = Client()
    body = _decode(client.get("/main/series_capture/?mode=series&shot=3&total=3"))
    assert 'class="series-banner"' in body
    assert "Next shot: 3 of 3" in body


def test_series_capture_renders_next_shot_for_arbitrary_index():
    client = Client()
    body = _decode(client.get("/main/series_capture/?mode=series&shot=2&total=4"))
    assert "Next shot: 2 of 4" in body


# ---------------------------------------------------------------------------
# shared CSS asset is loaded
# ---------------------------------------------------------------------------


def test_attract_loads_series_banner_css():
    client = Client()
    body = _decode(client.get("/main/attract/"))
    assert "css/series-banner.css" in body


def test_last_capture_loads_series_banner_css():
    client = Client()
    body = _decode(client.get("/main/last_capture/"))
    assert "css/series-banner.css" in body


def test_series_capture_loads_series_banner_css():
    client = Client()
    body = _decode(client.get("/main/series_capture/"))
    assert "css/series-banner.css" in body
