"""Scenarios: a run saved with its seed and commands replays exactly (SAVE, LOAD), and EXPORT."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.commands import REGISTRY, execute
from app.commands.registry import CommandResult
from app.config import Settings
from app.data.service import DataService
from app.db.session import make_engine, make_session_factory, upgrade_database
from app.sim.simulator import DEFAULT_SPEED, Simulator
from tests.support import make_india_anchors, make_us_anchors

MORNING = datetime(2026, 10, 20, 4, 0, tzinfo=UTC)  # Tuesday 09:30 in Mumbai


@pytest.fixture
def data(tmp_path: Path) -> Iterator[DataService]:
    url = f"sqlite:///{(tmp_path / 'scenarios.db').as_posix()}"
    engine = make_engine(url)
    upgrade_database(engine)
    overrides: dict[str, Any] = {
        "_env_file": None,
        "env": "test",
        "fred_api_key": None,
        "database_url": url,
        "data_dir": tmp_path,
        "scheduler_enabled": False,
        "offline": True,
        "sim_enabled": False,
    }
    yield DataService(Settings(**overrides), make_session_factory(engine), {})
    engine.dispose()


def run(sim: Simulator, text: str) -> CommandResult:
    return asyncio.run(execute(sim, text))


def state(sim: Simulator) -> dict[str, Any]:
    """Everything the markets would show: it must come back exactly after a LOAD."""
    assert sim.us is not None
    assert sim.india is not None
    m = sim.india
    return {
        "time": sim.sim_time,
        "curve": sim.us.par_curve(),
        "effr": sim.us.state.effr,
        "japan": sim.us.state.holdings["Japan"],
        "reserves": sim.us.state.sheet.reserves,
        "wacr": m.wacr(),
        "surplus": m.projected_surplus(),
        "corridor": (m.sdf, m.repo, m.msf),
        "history": [(d.day, d.wacr, d.surplus) for d in m.history],
        "auctions": [(a.at, a.result.allotted) for a in m.auctions],
        "balances": {code: b.balance for code, b in m.books.items()},
    }


def test_a_saved_run_replays_exactly(data: DataService) -> None:
    sim = Simulator(data, clock=lambda: MORNING)  # no fixed seed: the run draws its own
    sim.load(make_us_anchors(), make_india_anchors())
    sim.speed = DEFAULT_SPEED * 30
    # The live clock ticks unevenly; the replay will cut time up quite differently.
    script = [
        (7.3, "HIKE 25BP"),
        (13.1, "REPO -25BP"),
        (41.7, "SHOCK JP 100B 2D"),
        (0.4, "SPEED 10X"),  # not part of the scenario: speed never changes the path
        (33.3, "VRR 50000CR 7D"),
        (100.9, "CRR 3.5"),
        (2.0, "WACR POLICY"),
        (61.1, "WACR"),  # only shows the panel
        (87.6, None),
    ]
    for wall, text in script:
        sim.tick(wall)
        if text is not None:
            assert run(sim, text).ok, text
    assert [t for _, t in sim.journal] == [
        "HIKE 25BP",
        "REPO -25BP",
        "SHOCK JP 100B 2D",
        "VRR 50000CR 7D",
        "CRR 3.5",
        "WACR POLICY",
    ]
    saved = run(sim, "SAVE RUN1")
    assert saved.ok, saved.message
    assert f"seed {sim.seed}" in saved.message
    before, journal, seed = state(sim), list(sim.journal), sim.seed

    # Carry on and change things, then come back.
    sim.tick(200.0)
    run(sim, "CUT 50BP")
    assert state(sim) != before
    loaded = run(sim, "LOAD run1")
    assert loaded.ok, loaded.message
    assert loaded.data == {"refresh": True}
    assert (sim.seed, sim.journal) == (seed, journal)
    after = state(sim)
    for key, value in before.items():
        assert after[key] == value, key
    # Loading twice gives the same run again.
    run(sim, "LOAD RUN1")
    assert state(sim) == before


def test_listing_naming_and_guards(data: DataService) -> None:
    sim = Simulator(data, seed=4, clock=lambda: MORNING)
    sim.load(make_us_anchors(), make_india_anchors())
    assert run(sim, "LOAD").message == "No scenarios saved yet: SAVE name keeps this run"
    assert run(sim, "SAVE CALM").ok
    assert "replaced" in run(sim, "SAVE CALM").message
    assert run(sim, "SAVE ALT").ok
    listing = run(sim, "LOAD").message
    assert listing.startswith("Saved scenarios: ALT (0 commands")
    assert "CALM (0 commands" in listing
    for bad in ("SAVE", "SAVE A B", "SAVE $$", "LOAD NOPE"):
        assert not run(sim, bad).ok, bad
    sim.loading = "CALM"
    refused = run(sim, "HIKE 25BP")
    assert not refused.ok
    assert "is loading" in refused.message
    sim.loading = None


def test_scenarios_need_the_database() -> None:
    sim = Simulator(None, seed=4, clock=lambda: MORNING)
    sim.load(make_us_anchors(), make_india_anchors())
    result = run(sim, "SAVE CALM")
    assert not result.ok
    assert "database" in result.message


def test_each_run_has_a_seed_and_reset_starts_a_new_one() -> None:
    sim = Simulator(None, clock=lambda: MORNING)
    sim.load(make_us_anchors(), make_india_anchors())
    seeds = {sim.seed}
    for _ in range(3):
        reset = run(sim, "RESET")
        assert reset.data == {"refresh": True}
        assert f"seed {sim.seed}" in reset.message
        seeds.add(sim.seed)
    assert len(seeds) > 1  # fresh draws (all equal only by vanishing luck)
    fixed = Simulator(None, seed=9, clock=lambda: MORNING)
    fixed.load(make_us_anchors(), make_india_anchors())
    run(fixed, "RESET")
    assert fixed.seed == 9  # a configured seed is kept


def test_export_is_checked_here_and_done_in_the_browser() -> None:
    sim = Simulator(None, seed=4, clock=lambda: MORNING)
    for fmt in ("CSV", "PNG"):
        result = run(sim, f"EXPORT {fmt.lower()}")
        assert result.ok
        assert result.panel is None
        assert result.data == {"export": {"format": fmt.lower()}}
    assert not run(sim, "EXPORT PDF").ok
    assert all(spec.available for spec in REGISTRY.values())  # nothing is left for later
