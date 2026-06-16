"""Tests for ``photobooth.health.HealthMonitor`` (v0.5.0 Phase 4).

The monitor is the foundation for Phase 5 (unavailable mode + resume) and
Phase 6 (offline upload queue), so its three public behaviors are pinned
explicitly: poll-until-ready transitions, timeout fallback, and the
``recheck_loop`` that flips an ``unavailable`` component back to ``ready``
when its probe self-heals.

Probes are bare async closures driven by a call counter — no hardware
required.
"""

import asyncio

import pytest

from photobooth.health import (
    STATE_READY,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    HealthMonitor,
    StateChange,
)


@pytest.fixture
def monitor() -> HealthMonitor:
    return HealthMonitor()


async def test_register_seeds_unknown_state(monitor):
    async def probe():
        return True

    comp = monitor.register("widget", probe)
    assert comp.name == "widget"
    assert comp.state == STATE_UNKNOWN
    assert "widget" in monitor.names()


async def test_wait_until_ready_returns_when_probe_first_succeeds(monitor):
    calls = {"n": 0}

    async def probe():
        calls["n"] += 1
        return calls["n"] >= 3

    monitor.register("camera", probe)
    ready = await monitor.wait_until_ready("camera", interval=0.0)
    assert ready is True
    assert calls["n"] == 3
    assert monitor.is_ready("camera")


async def test_wait_until_ready_times_out_when_probe_never_succeeds(monitor):
    async def probe():
        return False

    monitor.register("camera", probe)
    ready = await monitor.wait_until_ready("camera", timeout=0.05, interval=0.01)
    assert ready is False
    assert monitor.get("camera").state == STATE_UNAVAILABLE


async def test_wait_until_ready_raises_for_unknown_component(monitor):
    with pytest.raises(KeyError):
        await monitor.wait_until_ready("nope", timeout=0.01)


async def test_probe_exception_treated_as_unavailable(monitor):
    async def probe():
        raise RuntimeError("usb gone")

    monitor.register("printer", probe)
    ready = await monitor.wait_until_ready("printer", timeout=0.02, interval=0.01)
    assert ready is False
    comp = monitor.get("printer")
    assert comp.state == STATE_UNAVAILABLE
    assert "usb gone" in (comp.last_error or "")


async def test_state_changes_published_for_each_transition(monitor):
    states = iter([False, False, True])

    async def probe():
        return next(states)

    monitor.register("camera", probe)
    await monitor.wait_until_ready("camera", interval=0.0)

    transitions = []
    while not monitor.state_changes.empty():
        transitions.append(monitor.state_changes.get_nowait())

    # Expected ordering: unknown -> unavailable -> ready (single de-duped
    # transition for the two consecutive False probes).
    assert [t.current for t in transitions] == [STATE_UNAVAILABLE, STATE_READY]
    assert transitions[0].previous == STATE_UNKNOWN
    assert transitions[1].previous == STATE_UNAVAILABLE
    assert all(isinstance(t, StateChange) for t in transitions)


async def test_recheck_loop_recovers_unavailable_component(monitor):
    flips = {"available": False}

    async def probe():
        return flips["available"]

    monitor.register("camera", probe)
    # Seed unavailable state via a one-shot failed wait.
    await monitor.wait_until_ready("camera", timeout=0.02, interval=0.01)
    assert monitor.get("camera").state == STATE_UNAVAILABLE

    # Drain any startup transitions so we can assert the recovery transition cleanly.
    while not monitor.state_changes.empty():
        monitor.state_changes.get_nowait()

    flips["available"] = True
    loop_task = asyncio.create_task(monitor.recheck_loop(interval=0.01))
    try:
        change = await asyncio.wait_for(monitor.state_changes.get(), timeout=1.0)
    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

    assert change.name == "camera"
    assert change.previous == STATE_UNAVAILABLE
    assert change.current == STATE_READY
    assert monitor.is_ready("camera")


async def test_recheck_loop_does_not_reprobe_ready_components(monitor):
    calls = {"n": 0}

    async def probe():
        calls["n"] += 1
        return True

    monitor.register("camera", probe)
    await monitor.wait_until_ready("camera", interval=0.0)
    assert calls["n"] == 1  # one probe call to reach ready

    loop_task = asyncio.create_task(monitor.recheck_loop(interval=0.01))
    await asyncio.sleep(0.05)
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    # The recheck loop only re-probes components in the unavailable state;
    # a ready component must not see additional probe calls.
    assert calls["n"] == 1


async def test_waiting_log_emitted_once(monitor, caplog):
    calls = {"n": 0}

    async def probe():
        calls["n"] += 1
        return calls["n"] >= 3

    monitor.register("camera", probe)
    caplog.set_level("INFO", logger="photobooth.health")
    await monitor.wait_until_ready("camera", interval=0.0)

    waiting = [r for r in caplog.records if "Waiting for camera" in r.getMessage()]
    assert len(waiting) == 1, "expected exactly one 'Waiting for <name>' line"

    ready = [r for r in caplog.records if "Component ready: camera" in r.getMessage()]
    assert len(ready) == 1
