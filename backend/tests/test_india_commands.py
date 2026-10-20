"""India function codes end to end against a simulator built on synthetic anchors."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.commands import execute
from app.commands.parser import CommandError, parse_inr_cr, parse_percent
from app.commands.registry import CommandResult
from app.sim.simulator import Simulator
from tests.support import make_india_anchors, make_us_anchors

MORNING = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)  # Tuesday 10:30 in Mumbai


@pytest.fixture
def sim() -> Simulator:
    simulator = Simulator(None, seed=3, clock=lambda: MORNING)
    simulator.load(make_us_anchors(), make_india_anchors())
    assert simulator.india is not None
    simulator.tick(3600 / simulator.speed)  # an hour of trading
    return simulator


def run(sim: Simulator, text: str) -> CommandResult:
    return asyncio.run(execute(sim, text))


def test_rupee_and_percent_parsers() -> None:
    assert parse_inr_cr("50000CR") == 50_000
    assert parse_inr_cr("1.5L") == 150_000
    assert parse_inr_cr("2LCR") == 200_000
    assert parse_percent("3.5") == pytest.approx(0.035)
    assert parse_percent("4%") == pytest.approx(0.04)
    for bad, parser in (("50000", parse_inr_cr), ("50B", parse_inr_cr), ("abc", parse_percent)):
        with pytest.raises(CommandError):
            parser(bad)


def test_panels_answer(sim: Simulator) -> None:
    for code in ("CALL", "WACR", "LAF", "NDTL", "TAXCAL"):
        result = run(sim, code)
        assert result.ok, result.message
        assert result.panel == code
    call = run(sim, "CALL")
    assert call.data is not None
    assert call.data["rounds"]
    assert call.message.startswith("WACR ")
    ndtl = run(sim, "NDTL")
    assert ndtl.data is not None
    assert ndtl.data["synthetic"] is True
    assert "SYNTHETIC" in ndtl.message
    corridor = run(sim, "CORR")
    assert corridor.data is not None
    assert corridor.data["india"]["repo"] == pytest.approx(0.055)


def test_policy_commands(sim: Simulator) -> None:
    repo = run(sim, "REPO +25BP")
    assert repo.ok, repo.message
    assert sim.india is not None
    assert sim.india.repo == pytest.approx(0.0575)
    assert "MSF 6.00%" in repo.message
    assert not run(sim, "REPO 300BP").ok
    crr = run(sim, "CRR 3.5")
    assert crr.ok, crr.message
    assert "fortnight beginning 01 Nov 2026" in crr.message
    assert "drains ₹1.39 lakh cr" in crr.message
    events = [e for e in sim.events.recent() if e.code in ("REPO", "CRR")]
    assert [e.kind for e in events] == ["policy", "policy"]


def test_ordering_an_auction(sim: Simulator) -> None:
    result = run(sim, "VRRR 50000CR 7D")
    assert result.ok, result.message
    assert "to absorb liquidity" in result.message
    assert result.data is not None
    assert result.data["runs_at"].startswith("2026-10-20T11:45")
    sim.tick(900 / sim.speed)  # through the next round
    assert any(e.code == "VRRR" and e.text.startswith("You ordered") for e in sim.events.recent())
    for bad in ("VRR", "VRR 50000", "VRR 50000CR 7Y", "VRR 20L"):
        assert not run(sim, bad).ok


def test_india_commands_need_the_india_market() -> None:
    only_us = Simulator(None)
    only_us.load(make_us_anchors())  # no data service: India cannot anchor
    assert only_us.india is None
    result = run(only_us, "CALL")
    assert not result.ok
    assert "India simulator is not running" in result.message
    assert only_us.status()["india"]["running"] is False
