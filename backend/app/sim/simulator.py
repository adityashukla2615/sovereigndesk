"""The simulator: a clock, the markets, the tick loop, invariants and published topics.

By default one wall-clock second is one simulated minute (``speed`` = 60 sim seconds per wall
second). Each tick advances the markets, asserts the invariants, and publishes ``us.tick``.
When the simulated date rolls over and newer real data has arrived, the markets re-anchor to it
while keeping every shock.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from app.data.service import DataService
from app.sim.anchors import USAnchors, build_us_anchors
from app.sim.events import Event, EventKind, EventLog, pct
from app.sim.pubsub import PubSub
from app.sim.us_market import USMarket

log = logging.getLogger(__name__)

DEFAULT_SPEED = 60.0
YEAR_SECONDS = 365.25 * 86400


class Simulator:
    def __init__(
        self,
        data: DataService | None,
        *,
        speed: float = DEFAULT_SPEED,
        tick_seconds: float = 0.25,
        seed: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.data = data
        self.speed = speed
        self.tick_seconds = tick_seconds
        self.seed = seed
        self.clock = clock
        self.bus = PubSub()
        self.events = EventLog()
        self.paused = False
        self.sim_time = clock()
        self.us: USMarket | None = None
        self.error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------ lifecycle

    def load(self, anchors: USAnchors | None = None) -> None:
        """Build the markets from real anchors (or the given ones); records why if it cannot."""
        try:
            anchors = anchors or build_us_anchors(self._require_data())
        except Exception as exc:  # surfaced to the UI rather than crashing the app
            self.error = f"{type(exc).__name__}: {exc}"
            self.us = None
            log.warning("simulator unavailable: %s", self.error)
            return
        self._rng = np.random.default_rng(self.seed)
        self.us = USMarket(anchors, self._rng)
        self.error = None
        self.sim_time = self.clock()
        self.events.clear()
        c = anchors.corridor
        self.emit(
            "info",
            "ANCHOR",
            f"Anchored to real data as of {anchors.as_of}: target range "
            f"{pct(c.lower)}–{pct(c.upper)}, "
            f"EFFR {pct(anchors.effr)}, 10Y {pct(anchors.par_curve['10Y'])}",
        )

    def _require_data(self) -> DataService:
        if self.data is None:
            raise RuntimeError("no data service")
        return self.data

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="simulator")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.tick_seconds)
            if self.paused or self.us is None:
                continue
            previous_day = self.sim_time.date()
            try:
                self.tick(self.tick_seconds)
            except AssertionError as exc:
                log.error("invariant violated, simulator paused: %s", exc)
                self.paused = True
                self.emit("warning", "INVARIANT", f"Simulator paused: {exc}")
                continue
            if self.sim_time.date() != previous_day:
                await self._maybe_reanchor()

    # ------------------------------------------------------------------ ticking

    def tick(self, wall_seconds: float) -> None:
        if self.us is None:
            return
        sim_seconds = wall_seconds * self.speed
        self.sim_time += timedelta(seconds=sim_seconds)
        for notice in self.us.step(sim_seconds / YEAR_SECONDS):
            self.emit("info", "US", notice)
        self.us.check_invariants()
        self.bus.publish("us.tick", self.us_payload())

    async def _maybe_reanchor(self) -> None:
        if self.data is None or self.us is None:
            return
        latest = self.data.latest_values(["ust/par/10Y"]).get("ust/par/10Y")
        if latest is None or latest[0] <= self.us.anchors.as_of:
            return
        try:
            anchors = await asyncio.to_thread(build_us_anchors, self.data)
        except Exception as exc:
            self.emit(
                "warning", "ANCHOR", f"Re-anchoring failed, keeping {self.us.anchors.as_of}: {exc}"
            )
            return
        self.us.reanchor(anchors)
        self.emit("info", "ANCHOR", f"Re-anchored to real data as of {anchors.as_of}; shocks kept")

    # ------------------------------------------------------------------ publishing

    def emit(
        self, kind: EventKind, code: str, text: str, data: dict[str, Any] | None = None
    ) -> Event:
        event = self.events.add(Event(self.sim_time, kind, code, text, data or {}))
        self.bus.publish("events", event.to_wire())
        return event

    def us_payload(self) -> dict[str, Any]:
        if self.us is None:
            return {}
        return {"sim_time": self.sim_time.isoformat(), **self.us.snapshot()}

    def status(self) -> dict[str, Any]:
        quality = self.us.anchors.quality if self.us else {}
        stale = sorted({label for label in quality.values() if label != "LIVE"})
        return {
            "running": self.us is not None,
            "error": self.error,
            "paused": self.paused,
            "speed": self.speed / DEFAULT_SPEED,
            "sim_time": self.sim_time.isoformat(),
            "anchored_as_of": self.us.anchors.as_of.isoformat() if self.us else None,
            "input_quality": stale or ["LIVE"],
        }

    def snapshot(self, topic: str) -> Any:
        """What a new subscriber receives first."""
        if topic == "us.tick":
            return self.us_payload() or None
        if topic == "events":
            return [e.to_wire() for e in self.events.recent()]
        if topic == "status":
            return self.status()
        return None
