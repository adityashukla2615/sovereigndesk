"""The US → India linkage on the simulators: calibration on synthetic series, SHOCK FED end to
end, RBI's responses in the money market, and the LINK panel."""

import asyncio
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.commands import execute
from app.sim.india_market import IST, is_business_day
from app.sim.linkage import (
    LinkAssumptions,
    LinkModel,
    fit_absorption,
    fit_flows,
    fit_rupee,
    fit_spillover,
)
from app.sim.simulator import Simulator
from sovereign_engine.linkage import LinkParams
from tests.support import make_india_anchors, make_us_anchors

MORNING = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)  # Tuesday 10:30 in Mumbai
PARAMS = LinkParams(
    spillover=0.2, debt_flow=5.0, equity_flow=-4.0, risk_flow=-0.3, intervention=0.6, inr_per_bn=0.2
)


def _model(params: LinkParams = PARAMS) -> LinkModel:
    return LinkModel(
        params=params,
        estimates=(),
        inr=88.0,
        inr_as_of=date(2026, 10, 19),
        reserves_bn=700.0,
        reserves_as_of=date(2026, 10, 16),
        assumptions=LinkAssumptions(),
    )


def _simulator() -> Simulator:
    sim = Simulator(None, seed=3, clock=lambda: MORNING)
    sim.load(make_us_anchors(), make_india_anchors())
    sim.link = _model()
    return sim


def _run(sim: Simulator, text: str) -> dict:  # type: ignore[type-arg]
    reply = asyncio.run(execute(sim, text))
    assert reply.ok, reply.message
    assert reply.data is not None
    return reply.data


def _advance(sim: Simulator, days: float) -> None:
    assert sim.india is not None
    sim.sim_time += timedelta(days=days)
    for n in sim.india.advance(sim.sim_time):
        sim.emit(n.kind, n.code, n.text, n.data)
    sim.india.check_invariants()


# ----------------------------------------------------------------------- calibration


def test_calibration_recovers_known_coefficients() -> None:
    rng = np.random.default_rng(9)
    days = pd.bdate_range("2014-01-01", "2026-09-30")
    us = pd.Series(2.5 + np.cumsum(rng.normal(0, 0.05, days.size)), index=days)
    noise = np.cumsum(rng.normal(0, 0.02, days.size))
    india = pd.Series(7.0 + 0.3 * (us - 2.5) + noise, index=days)
    spill = fit_spillover(india, us, lags=4)
    assert spill.value == pytest.approx(0.3, abs=0.06)
    assert spill.low < 0.3 < spill.high
    # Monthly flows built from the differential's and VIX's monthly changes.
    vix = pd.Series(18 + np.cumsum(rng.normal(0, 0.3, days.size)), index=days)
    months = pd.date_range("2014-01-01", "2026-09-01", freq="MS")
    in_m = india.resample("MS").mean()
    diff = (in_m - us.resample("MS").mean()).diff()
    d_us = us.resample("MS").mean().diff()
    d_vix = vix.resample("MS").mean().diff()
    debt_m = (4.0 * diff - 0.2 * d_vix + rng.normal(0, 0.3, months.size)).fillna(0.0)
    equity_m = (-3.0 * d_us - 0.4 * d_vix + rng.normal(0, 0.3, months.size)).fillna(0.0)

    def daily(monthly: pd.Series) -> pd.Series:  # spread each month's flow (US$ mn) over its days
        per_day = monthly.reindex(days, method="ffill") / days.to_series().dt.to_period("M").map(
            days.to_series().dt.to_period("M").value_counts()
        )
        return per_day * 1000

    debt, equity, risk = fit_flows(daily(debt_m), daily(equity_m), in_m, us, vix, lags=3)
    assert debt.value == pytest.approx(4.0, abs=0.5)
    assert equity.value == pytest.approx(-3.0, abs=0.5)
    assert risk.value == pytest.approx(-0.6, abs=0.15)
    # Weekly: reserves absorb 60% of flows; the rupee moves 0.08% per US$ bn of flows.
    weeks = pd.date_range("2014-01-03", "2026-09-25", freq="W-FRI")
    fpi_w = pd.Series(rng.normal(0, 1.0, weeks.size), index=weeks)
    dxy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.005, weeks.size))), index=weeks)
    fca_change = 0.6 * fpi_w + rng.normal(0, 0.3, weeks.size)
    fca = pd.Series(500 + np.cumsum(fca_change), index=weeks) * 1000
    inr = pd.Series(
        70 * np.exp(np.cumsum(-0.0008 * fpi_w + rng.normal(0, 0.001, weeks.size))), index=weeks
    )
    fpi_daily = fpi_w * 1000  # one reporting day a week is enough
    absorbed = fit_absorption(fca, fpi_daily, dxy, inr, lags=4)
    assert absorbed.value == pytest.approx(0.6, abs=0.06)
    rupee = fit_rupee(inr, fpi_daily, dxy, fca, absorbed.used, lags=4, cap=2.0)
    assert rupee.value == pytest.approx(0.08 / (1 - absorbed.used), rel=0.15)


# ----------------------------------------------------------------------- SHOCK FED


def test_shock_fed_runs_from_the_fed_to_wacr() -> None:
    sim = _simulator()
    assert sim.us is not None
    assert sim.india is not None
    upper = sim.us.state.corridor.upper
    data = _run(sim, "SHOCK FED 50BP")
    assert sim.us.state.corridor.upper == pytest.approx(upper + 0.005)
    nodes = {n["key"]: n["value"] for n in data["nodes"]}
    assert nodes["us10y"] > 0
    assert nodes["differential"] < 0
    assert nodes["fpi"] < 0
    assert nodes["rbi"] == pytest.approx(0.6 * nodes["fpi"])
    assert nodes["inr"] > 0
    assert nodes["liquidity"] < 0
    assert data["mode"] == "run"
    assert data["progress"]["day"] == 0  # India takes it from the next business day
    first = date.fromisoformat(data["progress"]["dates"][0])
    assert first == date(2026, 10, 21)
    assert any(e.code == "LINK" for e in sim.events.recent())
    run = sim.link_runs[-1]
    # A week on: the drained rupees are out of the system, the rupee and reserves follow.
    _advance(sim, 7)
    applied = sum(1 for d in run.days if d <= sim.sim_day())
    assert applied == 5
    assert float(run.path.drain_cr[:applied].sum()) < 0
    assert sim.india.inr == pytest.approx(float(run.path.inr[applied - 1]))
    assert sim.india.reserves_bn == pytest.approx(float(run.path.reserves_bn[applied - 1]))
    panel = _run(sim, "LINK")
    assert panel["progress"]["day"] == 5
    assert panel["live"]["inr"] == pytest.approx(sim.india.inr)


def test_the_drain_reaches_bank_reserves(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the other autonomous flows switched off, banks lose exactly the chain's drain."""
    sim = _simulator()
    assert sim.india is not None
    india = sim.india
    monkeypatch.setattr(india, "_autonomous", lambda day: [])
    liquidity0 = india.system_liquidity()
    _run(sim, "SHOCK FED 50BP")
    run = sim.link_runs[-1]
    _advance(sim, 7)
    applied = sum(1 for d in run.days if d <= sim.sim_day())
    expected = float(run.path.drain_cr[:applied].sum())
    assert india.system_liquidity() - liquidity0 == pytest.approx(expected, rel=1e-9)


def test_responses_in_the_money_market() -> None:
    sim = _simulator()
    assert sim.india is not None
    repo = sim.india.repo
    _run(sim, "SHOCK FED 50BP HIKE")
    _advance(sim, 1.2)  # day 0 (Wednesday): the flows begin
    assert sim.india.repo == pytest.approx(repo)
    _advance(sim, 1.0)  # day 1: RBI hikes
    assert sim.india.repo == pytest.approx(repo + 0.0025)

    sim = _simulator()
    _run(sim, "SHOCK FED 100BP VRR VIX+5")
    run = sim.link_runs[-1]
    assert run.path.shock.vix == 5.0
    _advance(sim, 2.3)  # through Thursday 09:30, day 1's auction
    auctions = [a for a in sim.india.auctions if a.result.kind == "VRR"] if sim.india else []
    assert auctions, "the response's VRR ran at 09:30"


def test_link_preview_and_errors() -> None:
    sim = _simulator()
    preview = _run(sim, "LINK")
    assert preview["mode"] == "preview"
    assert preview["nodes"][0]["value"] == pytest.approx(25.0)
    swap = _run(sim, "LINK SWAP")
    assert swap["response"] == "swap"
    for text, error in (
        ("SHOCK FED", "Usage: SHOCK FED"),
        ("SHOCK FED 500BP", "between 1 and 200"),
        ("SHOCK FED 25BP MAYBE", "Unexpected MAYBE"),
        ("LINK NOW", "Unknown response NOW"),
    ):
        reply = asyncio.run(execute(sim, text))
        assert not reply.ok
        assert error in reply.message
    idle = Simulator(None, seed=3, clock=lambda: MORNING)
    idle.load(make_us_anchors(), make_india_anchors())
    reply = asyncio.run(execute(idle, "LINK"))
    assert not reply.ok
    assert "Linkage unavailable: no data service" in reply.message


def test_business_days_only() -> None:
    sim = _simulator()
    _run(sim, "SHOCK FED 25BP")
    run = sim.link_runs[-1]
    assert all(is_business_day(d) for d in run.days)
    assert len(run.days) == 30
    assert run.days[0] > MORNING.astimezone(IST).date()
