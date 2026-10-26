"""The MPC predictor's dataset and models on synthetic inputs: release lags, windows, fitting."""

import asyncio
import math
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from app.commands import execute
from app.sim.mpc import (
    FEATURES,
    MacroInputs,
    MpcParams,
    build_dataset,
    features_at,
    fit_mpc,
    mpc_panel,
    repo_on,
)
from app.sim.simulator import Simulator
from tests.support import make_india_anchors, make_us_anchors


def _daily(start: str, end: str, value: float | np.ndarray) -> pd.Series:
    days = pd.date_range(start, end, freq="D")
    return pd.Series(np.broadcast_to(value, days.shape).astype(float), index=days)


def _inputs(n_decisions: int = 40) -> MacroInputs:
    months = pd.date_range("2013-01-01", "2022-12-01", freq="MS")
    cpi = pd.Series(5 + 3 * np.sin(np.arange(months.size) / 6), index=months)
    decisions = pd.date_range("2015-01-15", periods=n_decisions, freq="60D")
    repo, level = [], 7.0
    for day in decisions:
        latest = cpi[cpi.index < day - pd.DateOffset(months=1)].iloc[-1]
        level += 0.25 if latest > 6.5 else -0.25 if latest < 3.5 else 0.0
        repo.append(level)
    repo_series = pd.Series(repo, index=decisions)
    quarters = pd.date_range("2013-04-01", "2022-10-01", freq="QS-APR")
    daily_repo = repo_series.reindex(pd.date_range("2014-12-01", "2022-12-31")).ffill().bfill()
    return MacroInputs(
        cpi=cpi,
        core=cpi - 0.5,
        gdp_growth=pd.Series(6.0, index=quarters),
        output_gap=pd.Series(0.0, index=quarters),
        fed=_daily("2014-01-01", "2022-12-31", 2.0),
        inr=_daily("2014-01-01", "2022-12-31", np.linspace(60, 80, 3287)),
        wacr=daily_repo - 0.1,
        surplus_pct=_daily("2014-12-01", "2022-12-31", 1.0),
        tbill=(daily_repo + 0.15)[pd.DatetimeIndex(daily_repo.index).day_of_week == 2],
        repo=repo_series,
        weights=(),
    )


PARAMS = MpcParams(backtest_start=15)


def test_cpi_and_gdp_count_only_once_released() -> None:
    inputs = _inputs()
    may = inputs.cpi[pd.Timestamp("2016-05-01")]
    april = inputs.cpi[pd.Timestamp("2016-04-01")]
    on_12th, _ = features_at(inputs, date(2016, 6, 12), params=PARAMS, last_change_bp=0)
    on_13th, _ = features_at(inputs, date(2016, 6, 13), params=PARAMS, last_change_bp=0)
    assert on_12th["cpi"] == pytest.approx(april)  # May's CPI comes out on 12 June
    assert on_13th["cpi"] == pytest.approx(may)
    # Apr-Jun 2016 grows 9%, released by the end of August.
    growth = inputs.gdp_growth.mask(inputs.gdp_growth.index == pd.Timestamp("2016-04-01"), 9.0)
    inputs_q = _replace(inputs, gdp_growth=growth)
    assert features_at(inputs_q, date(2016, 8, 31), params=PARAMS, last_change_bp=0)[0][
        "gdp"
    ] == pytest.approx(6.0)
    assert features_at(inputs_q, date(2016, 9, 1), params=PARAMS, last_change_bp=0)[0][
        "gdp"
    ] == pytest.approx(9.0)


def _replace(inputs: MacroInputs, **changes: object) -> MacroInputs:
    fields = {name: getattr(inputs, name) for name in inputs.__dataclass_fields__}
    return MacroInputs(**(fields | changes))


def test_market_features_use_the_two_weeks_before() -> None:
    inputs = _inputs()
    day = date(2016, 3, 10)
    values, gap = features_at(inputs, day, params=PARAMS, last_change_bp=25.0)
    assert values["wacr_spread"] == pytest.approx(-10.0)  # WACR 10 bp under repo throughout
    assert values["tbill_spread"] == pytest.approx(15.0)
    assert values["liquidity"] == pytest.approx(1.0)
    assert values["fed_change"] == pytest.approx(0.0)
    assert values["inr_change"] > 0  # the rupee weakens along the synthetic path
    assert values["regime"] == 0.0  # before the MPC's first meeting
    assert values["last_change"] == 25.0
    assert gap == pytest.approx(0.0)
    later, _ = features_at(
        inputs, date(2017, 3, 10), params=PARAMS, last_change_bp=0, overrides={"liquidity": 2.5}
    )
    assert (later["regime"], later["liquidity"]) == (1.0, 2.5)
    assert repo_on(inputs, inputs.repo.index[3].date()) == pytest.approx(inputs.repo.iloc[3] / 100)
    with pytest.raises(Exception, match="no repo decision"):
        repo_on(inputs, date(2010, 1, 1))


def test_dataset_rows_classes_and_previous_moves() -> None:
    inputs = _inputs()
    scheduled = pd.Series(1.0, index=inputs.repo.index)
    data = build_dataset(inputs, scheduled, PARAMS)
    assert len(data.dates) == len(inputs.repo) - 1
    assert data.features.shape == (len(data.dates), len(FEATURES))
    np.testing.assert_allclose(data.change, np.diff(inputs.repo.to_numpy()) / 100)
    last = FEATURES.index("last_change")
    assert math.isnan(data.features[0, last])  # the first row's previous move is unknown
    np.testing.assert_allclose(data.features[1:, last], data.change[:-1] * 1e4)


def test_fit_backtest_forecast_and_panel() -> None:
    inputs = _inputs()
    scheduled = pd.Series(1.0, index=inputs.repo.index)
    scheduled.iloc[5] = 0.0
    meetings = (date(2022, 1, 1), date(2022, 3, 1))
    model = fit_mpc(inputs, scheduled, meetings, PARAMS)
    reports = model.backtest.reports
    assert set(reports) == {"ordered logit", "xgboost", "taylor", "repeat last", "always hold"}
    assert model.backtest.rows[0] == PARAMS.backtest_start
    assert reports["ordered logit"].accuracy >= reports["always hold"].accuracy
    assert model.next_meeting(date(2021, 12, 20)) == date(2022, 1, 1)
    assert model.next_meeting(date(2022, 6, 1)) is None
    panel = mpc_panel(
        model, day=date(2021, 12, 20), repo_now=0.06, last_change_bp=0.0, overrides={}
    )
    assert panel["next_meeting"] == "2022-01-01"
    for probs in panel["probabilities"].values():
        assert sum(probs) == pytest.approx(1.0)
        assert len(probs) == 5
    assert panel["sample"]["off_cycle"] == 1
    assert [f["key"] for f in panel["features"]] == list(FEATURES)
    assert panel["backtest"]["forecasts"] == len(inputs.repo) - 1 - PARAMS.backtest_start
    assert panel["taylor"]["pi_star"] == 0.04
    with pytest.raises(Exception, match="policy decisions on record"):
        build_dataset(_replace(inputs, repo=inputs.repo.iloc[:10]), scheduled, PARAMS)


def test_window_excludes_the_decision_day_itself() -> None:
    inputs = _inputs()
    day = inputs.repo.index[10].date()
    # The decision day's own print must not leak in.
    wacr = inputs.wacr.mask(inputs.wacr.index == pd.Timestamp(day), 99.0)
    values, _ = features_at(_replace(inputs, wacr=wacr), day, params=PARAMS, last_change_bp=0)
    assert values["wacr_spread"] == pytest.approx(-10.0)


MORNING = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)  # Tuesday 10:30 in Mumbai


def _simulator(model: bool = True) -> Simulator:
    sim = Simulator(None, seed=3, clock=lambda: MORNING)
    sim.load(make_us_anchors(), make_india_anchors())
    if model:
        inputs = _inputs()
        sim.mpc = fit_mpc(inputs, pd.Series(1.0, index=inputs.repo.index), (), PARAMS)
    return sim


def test_mpc_command_reads_the_simulation() -> None:
    sim = _simulator()
    reply = asyncio.run(execute(sim, "MPC"))
    assert reply.ok, reply.message
    assert reply.panel == "MPC"
    assert reply.data is not None
    features = {f["key"]: f["now"] for f in reply.data["features"]}
    assert sim.india is not None
    assert features["liquidity"] == pytest.approx(sim.india.surplus_pct())
    assert features["fed_funds"] == pytest.approx(sim.us.state.effr * 100 if sim.us else 0)
    asyncio.run(execute(sim, "REPO +25BP"))
    after = asyncio.run(execute(sim, "MPC"))
    assert after.data is not None
    moved = {f["key"]: f["now"] for f in after.data["features"]}
    assert moved["last_change"] == pytest.approx(25.0)  # the simulation's own decision
    assert after.data["taylor"]["repo"] == pytest.approx(sim.india.repo)


def test_mpc_command_explains_a_missing_predictor() -> None:
    sim = _simulator(model=False)
    reply = asyncio.run(execute(sim, "MPC"))
    assert not reply.ok
    assert "MPC predictor unavailable: no data service" in reply.message
