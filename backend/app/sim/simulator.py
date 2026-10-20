"""The simulator: a clock, the markets, the tick loop, invariants and published topics.

By default one wall-clock second is one simulated minute (``speed`` = 60 sim seconds per wall
second). Each tick advances the US and Indian markets, asserts their invariants, and publishes
``us.tick`` and ``in.tick``. The two markets are built independently: if one cannot anchor to
real data, the other still runs. When the simulated date rolls over and newer US data has
arrived, the US market re-anchors to it while keeping every shock. Each simulated business
day's G-sec close is paired with the US 10-year at that moment for the SPRD chart.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np

from app.data.service import DataService
from app.sim.anchors import USAnchors, build_us_anchors
from app.sim.events import Event, EventKind, EventLog, inr_cr, pct
from app.sim.india_anchors import INAnchors, build_india_anchors
from app.sim.india_market import IST, IndiaMarket
from app.sim.linkage import LinkModel, LinkRun, build_link
from app.sim.mpc import MpcModel, build_mpc
from app.sim.pubsub import PubSub
from app.sim.us_market import USMarket

log = logging.getLogger(__name__)

DEFAULT_SPEED = 60.0
YEAR_SECONDS = 365.25 * 86400


@dataclass(frozen=True, slots=True)
class SpreadPoint:
    day: date
    india: float
    """India 10Y par yield at the simulated close (decimal)."""
    us: float | None
    """US 10Y par yield at the same moment (decimal), if the US market runs."""


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
        self.india: IndiaMarket | None = None
        self.india_error: str | None = None
        self.spreads: list[SpreadPoint] = []
        self.mpc: MpcModel | None = None
        """The MPC predictor, fitted on first use (several seconds, off the event loop)."""
        self.mpc_error: str | None = None
        self._mpc_lock = asyncio.Lock()
        self.link: LinkModel | None = None
        """The US → India linkage, calibrated on first use."""
        self.link_error: str | None = None
        self._link_lock = asyncio.Lock()
        self.link_runs: list[LinkRun] = []
        """The US shocks run through the linkage since the markets were built."""
        self._task: asyncio.Task[None] | None = None
        self._rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------ lifecycle

    def load(
        self, anchors: USAnchors | None = None, india_anchors: INAnchors | None = None
    ) -> None:
        """Build the markets from real anchors (or the given ones); records why if one cannot."""
        self.sim_time = self.clock()
        self.events.clear()
        self.spreads = []
        self.mpc, self.mpc_error = None, None
        self.link, self.link_error = None, None
        self.link_runs = []
        self._rng = np.random.default_rng(self.seed)
        try:
            anchors = anchors or build_us_anchors(self._require_data())
        except Exception as exc:  # surfaced to the UI rather than crashing the app
            self.error = f"{type(exc).__name__}: {exc}"
            self.us = None
            log.warning("US simulator unavailable: %s", self.error)
        else:
            self.us = USMarket(anchors, self._rng)
            self.error = None
            c = anchors.corridor
            self.emit(
                "info",
                "ANCHOR",
                f"Anchored to real data as of {anchors.as_of}: target range "
                f"{pct(c.lower)}–{pct(c.upper)}, "
                f"EFFR {pct(anchors.effr)}, 10Y {pct(anchors.par_curve['10Y'])}",
            )
        try:
            india_anchors = india_anchors or build_india_anchors(self._require_data())
        except Exception as exc:
            self.india_error = f"{type(exc).__name__}: {exc}"
            self.india = None
            log.warning("India simulator unavailable: %s", self.india_error)
        else:
            # A stream of its own, so India's draws never shift the US path for a given seed.
            rng = np.random.default_rng(None if self.seed is None else self.seed + 1)
            self.india = IndiaMarket(india_anchors, rng, self.sim_time)
            self.india_error = None
            a = india_anchors
            self.emit(
                "info",
                "ANCHOR",
                f"India anchored to RBI data as of {a.as_of}: repo {pct(a.repo)} "
                f"(SDF {pct(a.sdf)}, MSF {pct(a.msf)}), surplus {inr_cr(a.surplus)} "
                f"({a.surplus_pct:.2f}% of NDTL), WACR {pct(a.wacr)} on {a.wacr_as_of}; "
                f"{len(self.india.books)} SYNTHETIC banks",
            )
            if a.gsec is not None:
                g = a.gsec
                self.emit(
                    "info",
                    "ANCHOR",
                    f"G-sec curve from FBIL as of {g.as_of}: 2Y {pct(g.close['2Y'])}, "
                    f"10Y {pct(g.close['10Y'])}, 30Y {pct(g.close['30Y'])}; pass-through from "
                    f"{len(g.events)} repo changes since April 2022",
                )
            else:
                self.emit("warning", "ANCHOR", f"G-sec curve unavailable: {a.gsec_error}")

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
            if self.paused or (self.us is None and self.india is None):
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
        if self.us is None and self.india is None:
            return
        sim_seconds = wall_seconds * self.speed
        self.sim_time += timedelta(seconds=sim_seconds)
        if self.us is not None:
            for notice in self.us.step(sim_seconds / YEAR_SECONDS):
                self.emit("info", "US", notice)
            self.us.check_invariants()
            self.bus.publish("us.tick", self.us_payload())
        if self.india is not None:
            for n in self.india.advance(self.sim_time):
                self.emit(n.kind, n.code, n.text, n.data)
            self.india.check_invariants()
            self._record_spreads()
            self.bus.publish("in.tick", self.india_payload())

    async def mpc_model(self) -> MpcModel | None:
        """The fitted MPC predictor, built from the data on first use; None (with the reason in
        ``mpc_error``) when the data cannot support it."""
        async with self._mpc_lock:
            if self.mpc is None and self.mpc_error is None:
                if self.data is None:
                    self.mpc_error = "no data service"
                else:
                    try:
                        self.mpc = await asyncio.to_thread(build_mpc, self.data)
                    except Exception as exc:  # surfaced to the user rather than raised
                        self.mpc_error = f"{type(exc).__name__}: {exc}"
                        log.warning("MPC predictor unavailable: %s", self.mpc_error)
            return self.mpc

    async def link_model(self) -> LinkModel | None:
        """The calibrated linkage, built from the data on first use; None (with the reason in
        ``link_error``) when the data cannot support it."""
        async with self._link_lock:
            if self.link is None and self.link_error is None:
                if self.data is None:
                    self.link_error = "no data service"
                else:
                    try:
                        self.link = await asyncio.to_thread(build_link, self.data)
                    except Exception as exc:  # surfaced to the user rather than raised
                        self.link_error = f"{type(exc).__name__}: {exc}"
                        log.warning("linkage unavailable: %s", self.link_error)
            return self.link

    def sim_day(self) -> date:
        return self.sim_time.astimezone(IST).date()

    def _record_spreads(self) -> None:
        curve = self.india.gsec if self.india is not None else None
        if curve is None:
            return
        last = self.spreads[-1].day if self.spreads else None
        us = self.us.par_curve()["10Y"] if self.us is not None else None
        for close in curve.history:
            if last is None or close.day > last:
                self.spreads.append(SpreadPoint(close.day, close.par["10Y"], us))
        self.spreads = self.spreads[-400:]

    def spread_panel(self) -> dict[str, Any] | None:
        """SPRD: India 10Y against US 10Y, real history and simulated closes, and the spread now."""
        curve = self.india.gsec if self.india is not None else None
        if curve is None:
            return None
        a = curve.anchors
        india = curve.points["10Y"]
        us = self.us.par_curve()["10Y"] if self.us is not None else None
        return {
            "real": [{"date": d.isoformat(), "india": i, "us": u} for d, i, u in a.spread_history],
            "simulated": [
                {"date": s.day.isoformat(), "india": s.india, "us": s.us} for s in self.spreads
            ],
            "now": {"india": india, "us": us, "spread": None if us is None else india - us},
            "daily_from": a.daily_from.isoformat(),
            "india_as_of": a.as_of.isoformat(),
            "us_as_of": self.us.anchors.as_of.isoformat() if self.us is not None else None,
        }

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

    def india_payload(self) -> dict[str, Any]:
        if self.india is None:
            return {}
        return {"sim_time": self.sim_time.isoformat(), **self.india.snapshot()}

    def status(self) -> dict[str, Any]:
        quality = self.us.anchors.quality if self.us else {}
        stale = sorted({label for label in quality.values() if label != "LIVE"})
        india_quality = self.india.anchors.quality if self.india else {}
        india_stale = sorted({label for label in india_quality.values() if label != "LIVE"})
        return {
            "running": self.us is not None,
            "error": self.error,
            "paused": self.paused,
            "speed": self.speed / DEFAULT_SPEED,
            "sim_time": self.sim_time.isoformat(),
            "anchored_as_of": self.us.anchors.as_of.isoformat() if self.us else None,
            "input_quality": stale or ["LIVE"],
            "india": {
                "running": self.india is not None,
                "error": self.india_error,
                "anchored_as_of": self.india.anchors.as_of.isoformat() if self.india else None,
                "input_quality": india_stale or ["LIVE"],
            },
        }

    def snapshot(self, topic: str) -> Any:
        """What a new subscriber receives first."""
        if topic == "us.tick":
            return self.us_payload() or None
        if topic == "in.tick":
            return self.india_payload() or None
        if topic == "events":
            return [e.to_wire() for e in self.events.recent()]
        if topic == "status":
            return self.status()
        return None
