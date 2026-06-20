"""Tests for the v0.5.0 Phase 4 startup dependency wait.

Pre-Phase-4, ``_startup`` raised at the first failed component init, so a
booth cold-booted with the camera USB unplugged would crash the service
and rely on systemd to restart it on a tight loop. Phase 4 inserts a
``HealthMonitor`` between hardware detection and instantiation: each
component is registered with an async probe, and ``_startup`` calls
``wait_until_ready`` before the actual ``add_*`` instantiation. A
component that's missing at boot is waited-for, with a
``"Waiting for <name>"`` line in the journal, instead of crashing.

These tests stub every hardware-touching surface so ``_startup`` can be
exercised on a non-Pi dev machine. The probes are patched at the
``booth_main`` namespace (where they're imported into) so we control
their pass/fail behavior turn-by-turn.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# ``booth_main`` does ``import board`` at module top, and its Phase 4
# probe imports transitively pull in ``neopixel`` (the rpi_ws281x
# binding). Both are Pi-only; stub them here so the test module loads
# on a dev machine.
sys.modules.setdefault("board", MagicMock())
sys.modules.setdefault("neopixel", MagicMock())

from photobooth import booth_main  # noqa: E402 — post-stub import
from photobooth.booth_main import PhotoBooth  # noqa: E402


@pytest.fixture
def booth(monkeypatch):
    """A bare ``PhotoBooth`` with every ``self.rpi.*`` call stubbed.

    The bare instance has no attributes yet — ``_startup`` populates
    ``self.panel`` / ``self.camera`` / ``self.printer`` via the mocked
    ``add_*`` factories.
    """
    b = PhotoBooth()
    b.rpi = MagicMock()
    b.rpi.start_web = AsyncMock()
    b.rpi.start_kiosk = AsyncMock()
    b.rpi.reset_last_shot = MagicMock()
    b.rpi.toggle_led = MagicMock()

    panel_mock = MagicMock()
    panel_mock.panel_test = AsyncMock()
    b.rpi.add_neopixel = MagicMock(return_value=panel_mock)
    b.rpi.add_camera = MagicMock(return_value=MagicMock())
    b.rpi.add_printer = MagicMock(return_value=MagicMock())

    # Shorten timeouts so failure paths complete in test-time.
    monkeypatch.setattr(booth_main, "HEALTH_TIMEOUT_WEB", 1.0)
    monkeypatch.setattr(booth_main, "HEALTH_TIMEOUT_NEOPIXEL", 1.0)
    monkeypatch.setattr(booth_main, "HEALTH_TIMEOUT_CAMERA", 1.0)
    monkeypatch.setattr(booth_main, "HEALTH_TIMEOUT_PRINTER", 1.0)
    monkeypatch.setattr(booth_main, "HEALTH_TIMEOUT_NET_LOCAL", 0.05)
    monkeypatch.setattr(booth_main, "HEALTH_TIMEOUT_NET_WWW", 0.05)
    # Recheck loop runs as a background task; keep its first sleep long so
    # it never fires during the test window.
    monkeypatch.setattr(booth_main, "HEALTH_RECHECK_INTERVAL", 100.0)

    return b


def _always_true():
    async def probe():
        return True

    return probe


def _always_false():
    async def probe():
        return False

    return probe


def _flips_after(n):
    state = {"calls": 0}

    async def probe():
        state["calls"] += 1
        return state["calls"] >= n

    return probe, state


async def _stop_recheck(booth):
    task = getattr(booth, "_recheck_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.fixture
def patch_probes_ready(monkeypatch):
    """All probes return True immediately — the happy path."""
    monkeypatch.setattr(booth_main, "probe_web_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_neopixel_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_camera_available", lambda model: _always_true()())
    monkeypatch.setattr(booth_main, "probe_printer_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_local_network", _always_true())
    monkeypatch.setattr(booth_main, "probe_internet_available", _always_true())


async def test_startup_happy_path(booth, patch_probes_ready):
    await booth._startup()
    try:
        assert booth.rpi.add_neopixel.called
        assert booth.rpi.add_camera.called
        assert booth.rpi.add_printer.called
        assert booth.health.is_ready("camera")
        assert booth.health.is_ready("neopixel")
        assert booth.health.is_ready("printer")
        assert booth.health.is_ready("web")
    finally:
        await _stop_recheck(booth)


async def test_startup_waits_for_camera(booth, monkeypatch, caplog):
    """A camera that's missing for the first two probe calls is waited
    for, not crashed on. ``add_camera`` is only invoked once the probe
    flips to ready, and the journal shows a ``Waiting for camera`` line.
    """
    monkeypatch.setattr(booth_main, "probe_web_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_neopixel_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_printer_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_local_network", _always_true())
    monkeypatch.setattr(booth_main, "probe_internet_available", _always_true())

    camera_probe, state = _flips_after(3)

    async def camera_probe_with_model(model):
        return await camera_probe()

    monkeypatch.setattr(booth_main, "probe_camera_available", camera_probe_with_model)

    caplog.set_level("INFO", logger="photobooth.health")

    # Shorten wait_until_ready's between-attempt sleep so the test
    # completes quickly. We patch asyncio.sleep at the health module
    # level so the per-call interval drops to zero.
    real_sleep = asyncio.sleep

    async def fast_sleep(t):
        await real_sleep(0)

    monkeypatch.setattr("photobooth.health.asyncio.sleep", fast_sleep)

    try:
        await booth._startup()
        assert state["calls"] == 3, "camera probe should have polled 3 times"
        assert booth.rpi.add_camera.called
        assert booth.rpi.add_camera.call_count == 1
        waiting = [r for r in caplog.records if "Waiting for camera" in r.getMessage()]
        assert waiting, "expected a 'Waiting for camera' log line"
    finally:
        await _stop_recheck(booth)


async def test_startup_does_not_call_add_camera_until_probe_passes(booth, monkeypatch):
    """Ordering invariant: ``add_camera`` must never run while the camera
    probe is still returning False. A regression here would mean the
    booth tries to open gphoto2 against a device that isn't enumerated."""
    monkeypatch.setattr(booth_main, "probe_web_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_neopixel_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_printer_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_local_network", _always_true())
    monkeypatch.setattr(booth_main, "probe_internet_available", _always_true())

    add_camera_calls = []

    def fake_add_camera(**kwargs):
        add_camera_calls.append(kwargs)
        return MagicMock()

    booth.rpi.add_camera = fake_add_camera

    probe_calls = {"n": 0}
    target_call = 4

    async def camera_probe(model):
        probe_calls["n"] += 1
        assert not add_camera_calls, (
            f"add_camera was invoked before probe ready " f"(probe call #{probe_calls['n']})"
        )
        return probe_calls["n"] >= target_call

    monkeypatch.setattr(booth_main, "probe_camera_available", camera_probe)

    # Capture the real asyncio.sleep before patching so the fast_sleep
    # shim doesn't recurse through the monkeypatched name.
    real_sleep = asyncio.sleep

    async def fast_sleep(t):
        await real_sleep(0)

    monkeypatch.setattr("photobooth.health.asyncio.sleep", fast_sleep)

    try:
        await booth._startup()
        assert probe_calls["n"] == target_call
        assert len(add_camera_calls) == 1
    finally:
        await _stop_recheck(booth)


async def test_startup_continues_when_internet_optional_fails(booth, monkeypatch):
    """Internet is optional: a permanently-failing probe must not raise,
    and the LED for ``net_www`` must stay off."""
    monkeypatch.setattr(booth_main, "probe_web_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_neopixel_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_camera_available", lambda m: _always_true()())
    monkeypatch.setattr(booth_main, "probe_printer_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_local_network", _always_false())
    monkeypatch.setattr(booth_main, "probe_internet_available", _always_false())

    try:
        await booth._startup()
        labels = [c.kwargs.get("label") for c in booth.rpi.toggle_led.mock_calls]
        # Optional probes failed → their LEDs should not have been turned on.
        assert "net_local" not in labels
        assert "net_www" not in labels
        # Required LEDs still fire.
        assert "camera_rdy" in labels
        assert "print_rdy" in labels
        assert "shutter_rdy" in labels
    finally:
        await _stop_recheck(booth)


async def test_startup_raises_when_required_camera_never_ready(booth, monkeypatch):
    """When the camera probe times out, the required-dep contract is to
    raise so systemd will restart the service rather than entering a
    half-initialized state."""
    monkeypatch.setattr(booth_main, "probe_web_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_neopixel_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_camera_available", lambda m: _always_false()())
    monkeypatch.setattr(booth_main, "probe_printer_available", _always_true())
    monkeypatch.setattr(booth_main, "probe_local_network", _always_true())
    monkeypatch.setattr(booth_main, "probe_internet_available", _always_true())

    real_sleep = asyncio.sleep

    async def fast_sleep(t):
        await real_sleep(0)

    monkeypatch.setattr("photobooth.health.asyncio.sleep", fast_sleep)

    with pytest.raises(RuntimeError, match="Camera"):
        await booth._startup()
    # No recheck task should have been started — startup raised first.
    assert not hasattr(booth, "_recheck_task") or booth._recheck_task is None
