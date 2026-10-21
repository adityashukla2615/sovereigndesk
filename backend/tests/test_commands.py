"""Function codes end to end against a simulator built on synthetic anchors."""

import asyncio

import pytest

from app.commands import REGISTRY, catalog, execute
from app.commands.parser import (
    CommandError,
    parse_bp,
    parse_days,
    parse_speed,
    parse_usd_bn,
    resolve_country,
    tokenize,
)
from app.sim.simulator import DEFAULT_SPEED, Simulator
from tests.support import make_us_anchors


@pytest.fixture
def sim() -> Simulator:
    simulator = Simulator(None, seed=11)
    simulator.load(make_us_anchors())
    return simulator


def run(sim: Simulator, text: str):  # type: ignore[no-untyped-def]
    return asyncio.run(execute(sim, text))


# ----------------------------------------------------------------------- parsing


def test_token_parsers() -> None:
    assert tokenize("  shock jp 200b  ").args == ("JP", "200B")
    assert parse_bp("25BP") == pytest.approx(0.0025)
    assert parse_bp("-50BP") == pytest.approx(-0.005)
    assert parse_bp("10") == pytest.approx(0.001)
    assert parse_usd_bn("200B") == 200
    assert parse_usd_bn("1.5T") == 1500
    assert parse_days("10D") == 10
    assert parse_days("2W") == 14
    assert parse_speed("10X") == 10
    for bad, parser in (
        ("25%", parse_bp),
        ("lots", parse_usd_bn),
        ("10Y", parse_days),
        ("0X", parse_speed),
    ):
        with pytest.raises(CommandError):
            parser(bad)


def test_country_resolution() -> None:
    holdings = {"Japan": 1068.3, "China, Mainland": 590.7}
    assert resolve_country("JP", holdings) == "Japan"
    assert resolve_country("JAPAN", holdings) == "Japan"
    with pytest.raises(CommandError, match="Try one of: CN, JP"):
        resolve_country("XX", holdings)


# ----------------------------------------------------------------------- registry


def test_registry_lists_every_planned_function() -> None:
    codes = {c["code"] for c in catalog()}
    assert {"PY", "UST", "FED", "HIKE", "CUT", "QT", "DEBT", "TIC", "SHOCK", "CORR"} <= codes
    assert {"CALL", "WACR", "LAF", "MPC", "LINK", "REPLAY", "HELP", "SPEED"} <= codes
    assert REGISTRY["WACR"].available
    assert REGISTRY["MPC"].available
    assert REGISTRY["LINK"].available
    assert REGISTRY["IMPACT"].available
    assert REGISTRY["REPLAY"].available
    assert not REGISTRY["CCIL"].available
    assert REGISTRY["PY"].available


def test_unknown_and_planned_codes(sim: Simulator) -> None:
    unknown = run(sim, "UTS")
    assert not unknown.ok
    assert "Did you mean UST?" in unknown.message
    later = run(sim, "CCIL")
    assert not later.ok
    assert "Phase 12" in later.message
    assert not run(sim, "").ok


def test_market_commands_need_a_running_simulator() -> None:
    idle = Simulator(None)
    idle.load()  # no data service: records why instead of raising
    assert idle.us is None
    result = run(idle, "UST")
    assert not result.ok
    assert "not running" in result.message
    assert run(idle, "HELP").ok  # system functions still work


# ----------------------------------------------------------------------- US functions


def test_py_ust_fed_tic_corr(sim: Simulator) -> None:
    py = run(sim, "PY 10Y")
    assert py.ok
    assert py.panel == "PY"
    assert py.data is not None
    assert len(py.data["exact"]) == len(py.data["shifts_bp"])
    assert not run(sim, "PY 3M").ok
    assert run(sim, "UST").message.startswith("2Y ")
    fed = run(sim, "FED")
    assert "Target range 3.75%–4.00%" in fed.message
    tic = run(sim, "TIC")
    assert tic.data is not None
    assert tic.data["holders"][0]["country"] == "Japan"
    assert "Grand Total" not in {h["country"] for h in tic.data["holders"]}
    assert run(sim, "CORR").ok


def test_hike_and_cut_emit_policy_events(sim: Simulator) -> None:
    hike = run(sim, "HIKE 25BP")
    assert hike.ok
    assert "target range 4.00%–4.25%" in hike.message
    event = sim.events.recent(1)[0]
    assert (event.kind, event.code) == ("policy", "HIKE")
    assert event.data["curve_change"]["2Y"] > event.data["curve_change"]["10Y"] > 0
    assert run(sim, "CUT 50BP").ok
    assert sim.us is not None
    assert sim.us.state.corridor.lower == pytest.approx(0.0350)
    assert not run(sim, "HIKE 500BP").ok
    assert not run(sim, "HIKE").ok


def test_qt_projection_and_off(sim: Simulator) -> None:
    qt = run(sim, "QT 95B")
    assert qt.ok
    assert "$60bn UST + $35bn MBS" in qt.message
    assert qt.data is not None
    assert len(qt.data["reserves"]) == 24
    assert sim.events.recent(1)[0].kind == "projection"
    assert run(sim, "QT OFF").ok
    assert sim.us is not None
    assert sim.us.state.qt.treasury_cap == 0
    assert not run(sim, "QT 9000B").ok


def test_shock_creates_an_order_and_narrative(sim: Simulator) -> None:
    result = run(sim, "SHOCK JP 200B 10D LONG")
    assert result.ok, result.message
    assert sim.us is not None
    (order,) = sim.us.state.orders
    assert (order.country, order.total, order.days) == ("Japan", 200, 10)
    assert "Japan sells $200bn of Treasuries (LONG) over 10 days" in result.message
    assert result.data is not None
    assert result.data["long_run"]["30Y"] > 0
    assert result.data["debt"]["delta_by_year"]["1"] > 0
    assert not run(sim, "SHOCK JP 5000B").ok  # more than Japan holds
    assert "SHOCK FED needs both markets running" in run(sim, "SHOCK FED 50BP").message
    assert not run(sim, "SHOCK JP 10B 5Q").ok


def test_debt_reports_both_curves(sim: Simulator) -> None:
    run(sim, "HIKE 100BP")
    debt = run(sim, "DEBT")
    assert debt.ok
    assert debt.data is not None
    assert debt.data["delta_by_year"]["1"] > 0
    assert "% of GDP" in debt.message


# ----------------------------------------------------------------------- system functions


def test_speed_pause_resume_reset(sim: Simulator) -> None:
    assert run(sim, "SPEED 10X").ok
    assert sim.speed == DEFAULT_SPEED * 10
    assert not run(sim, "SPEED 5000X").ok

    def paused() -> bool:  # read afresh: commands change it behind mypy's back
        return sim.paused

    assert run(sim, "PAUSE").ok
    assert paused()
    assert run(sim, "RESUME").ok
    assert not paused()
    run(sim, "SHOCK JP 100B")
    assert run(sim, "RESET").ok
    assert sim.us is not None
    assert sim.us.state.orders == []
    help_one = run(sim, "HELP SHOCK")
    assert "SHOCK JP 200B" in help_one.message
