"""Saved scenarios: a run's seed and start, and the commands that changed its markets.

A scenario replays exactly. The simulator's paths depend on simulated time only (see
``simulator.py``), so LOAD rebuilds the markets from the same anchors with the same seed at
the same start, runs each command at the simulated time it first ran, and stops where SAVE
was. If the anchors have moved on since (newer data), the replay starts from the new ones and
says so.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ScenarioRow
from app.db.session import as_utc

if TYPE_CHECKING:
    from app.sim.simulator import Simulator


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    seed: int
    started: datetime
    saved_at: datetime
    us_as_of: date | None
    india_as_of: date | None
    commands: tuple[tuple[datetime, str], ...]


def capture(sim: "Simulator", name: str) -> Scenario:
    """The scenario the simulator has run so far."""
    return Scenario(
        name=name,
        seed=sim.seed,
        started=sim.started,
        saved_at=sim.sim_time,
        us_as_of=sim.us.anchors.as_of if sim.us is not None else None,
        india_as_of=sim.india.anchors.as_of if sim.india is not None else None,
        commands=tuple(sim.journal),
    )


def _row(s: Scenario, now: datetime) -> ScenarioRow:
    return ScenarioRow(
        name=s.name,
        seed=s.seed,
        started=s.started,
        saved_at=s.saved_at,
        us_as_of=s.us_as_of,
        india_as_of=s.india_as_of,
        commands=json.dumps([{"at": at.isoformat(), "text": text} for at, text in s.commands]),
        created_at=now,
    )


def _scenario(row: ScenarioRow) -> Scenario:
    commands = tuple(
        (datetime.fromisoformat(c["at"]), str(c["text"])) for c in json.loads(row.commands)
    )
    return Scenario(
        name=row.name,
        seed=row.seed,
        started=as_utc(row.started),
        saved_at=as_utc(row.saved_at),
        us_as_of=row.us_as_of,
        india_as_of=row.india_as_of,
        commands=commands,
    )


def save(sessions: sessionmaker[Session], scenario: Scenario) -> bool:
    """Store a scenario under its name; True if it replaced one of that name."""
    with sessions.begin() as session:
        replaced = session.get(ScenarioRow, scenario.name) is not None
        session.merge(_row(scenario, datetime.now(UTC)))
    return replaced


def get(sessions: sessionmaker[Session], name: str) -> Scenario | None:
    with sessions() as session:
        row = session.get(ScenarioRow, name)
        return None if row is None else _scenario(row)


def saved(sessions: sessionmaker[Session]) -> list[Scenario]:
    """Every saved scenario, by name."""
    with sessions() as session:
        rows = session.scalars(select(ScenarioRow).order_by(ScenarioRow.name)).all()
        return [_scenario(r) for r in rows]
