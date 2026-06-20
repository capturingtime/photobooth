"""Component health monitoring for photobooth (v0.5.0 Phase 4).

``HealthMonitor`` coordinates async probes for hardware (camera, neopixel,
printer) and connectivity (web, local network, internet). Each component is
registered with an async ``probe`` callable that returns ``bool``; the
monitor polls the probe at a configurable interval and tracks the latest
state on a ``ComponentHealth`` record.

Two consumption paths:

* ``wait_until_ready(name, timeout=...)`` — block startup (or any caller)
  until a component reports ``ready``. Used by ``booth_main._startup``.
* ``recheck_loop(interval=...)`` — long-running background task that
  re-probes any component currently in the ``unavailable`` state. A
  component that self-heals (e.g. camera USB reconnected) flips back to
  ``ready`` without manual intervention.

Every state transition is published to ``state_changes`` (an
``asyncio.Queue`` of ``StateChange`` records) so downstream consumers
(Phase 5 unavailable-mode recovery, Phase 6 upload-queue worker) can
react to events without polling.

Probes must not raise — any exception is caught and treated as a
``False`` result, with the repr stored on ``ComponentHealth.last_error``.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


STATE_UNKNOWN = "unknown"
STATE_READY = "ready"
STATE_UNAVAILABLE = "unavailable"


ProbeCoro = Callable[[], Awaitable[bool]]


@dataclass
class ComponentHealth:
    name: str
    state: str = STATE_UNKNOWN
    last_error: Optional[str] = None
    last_checked: Optional[float] = None


@dataclass
class StateChange:
    name: str
    previous: str
    current: str
    last_error: Optional[str] = None


class HealthMonitor:
    """Registry of component probes with poll-based readiness tracking."""

    def __init__(self) -> None:
        self._components: Dict[str, ComponentHealth] = {}
        self._probes: Dict[str, ProbeCoro] = {}
        self.state_changes: asyncio.Queue = asyncio.Queue()

    def register(self, name: str, probe: ProbeCoro) -> ComponentHealth:
        """Register ``probe`` under ``name``. Idempotent re-registration replaces the probe."""
        if name not in self._components:
            self._components[name] = ComponentHealth(name=name)
        self._probes[name] = probe
        return self._components[name]

    def get(self, name: str) -> ComponentHealth:
        return self._components[name]

    def is_ready(self, name: str) -> bool:
        return self._components[name].state == STATE_READY

    def names(self) -> list:
        return list(self._components.keys())

    async def _probe_once(self, name: str) -> bool:
        """Invoke ``name``'s probe once, updating state and emitting transitions."""
        probe = self._probes[name]
        ok = False
        last_error: Optional[str] = None
        try:
            ok = bool(await probe())
        except Exception as exc:
            last_error = repr(exc)
            logger.debug("Probe '%s' raised: %s", name, exc)

        comp = self._components[name]
        comp.last_checked = time.time()
        comp.last_error = None if ok else (last_error or comp.last_error)

        await self._transition(name, STATE_READY if ok else STATE_UNAVAILABLE)
        return ok

    async def _transition(self, name: str, new_state: str) -> None:
        comp = self._components[name]
        if comp.state == new_state:
            return
        previous = comp.state
        comp.state = new_state
        logger.info("Component state: %s %s -> %s", name, previous, new_state)
        await self.state_changes.put(
            StateChange(
                name=name,
                previous=previous,
                current=new_state,
                last_error=comp.last_error,
            )
        )

    async def wait_until_ready(
        self,
        name: str,
        *,
        timeout: Optional[float] = None,
        interval: float = 1.0,
    ) -> bool:
        """Poll the probe for ``name`` until it returns True or ``timeout`` elapses.

        Returns True on ready, False on timeout. ``timeout=None`` waits
        forever. A single ``"Waiting for <name>"`` INFO line is emitted
        the first time a probe returns False, so the live booth journal
        clearly records the dependency the service is blocked on.
        """
        if name not in self._components:
            raise KeyError(f"Component '{name}' not registered")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout if timeout is not None else None
        logged_wait = False

        while True:
            if await self._probe_once(name):
                logger.info("Component ready: %s", name)
                return True

            if not logged_wait:
                logger.info("Waiting for %s", name)
                logged_wait = True

            if deadline is not None and loop.time() >= deadline:
                logger.warning("Component '%s' not ready after %.1fs", name, timeout)
                return False

            await asyncio.sleep(interval)

    async def recheck_loop(self, interval: float = 10.0) -> None:
        """Re-probe any component in the ``unavailable`` state every ``interval`` seconds.

        Intended to be launched once via ``asyncio.create_task`` after
        startup. Runs forever; cancel the task to stop. Components in
        ``ready`` or ``unknown`` are not re-probed — readiness is owned
        by the original caller of ``wait_until_ready``.
        """
        logger.info("Health recheck loop started (interval=%.1fs)", interval)
        try:
            while True:
                await asyncio.sleep(interval)
                for name, comp in list(self._components.items()):
                    if comp.state == STATE_UNAVAILABLE:
                        await self._probe_once(name)
        except asyncio.CancelledError:
            logger.info("Health recheck loop cancelled")
            raise
