"""Module D: replay scores and summaries, the fire-sale λ, and the chain on daily moves."""

import numpy as np
import pytest

from sovereign_engine.linkage import FedShock, LinkParams, MarketStart, replay_chain, run_chain
from sovereign_engine.replay import fit_lambda, move_per_unit, score, summarize


def test_scores_of_a_path() -> None:
    actual = np.array([0.0, 10.0, 25.0, 40.0, 30.0, 20.0])
    model = np.array([0.0, 8.0, 20.0, 28.0, 34.0, 26.0])
    s = score(model, actual)
    assert s.n == 6
    assert s.rmse == pytest.approx(np.sqrt(np.mean((model - actual) ** 2)))
    assert s.mae == pytest.approx(np.mean(np.abs(model - actual)))
    # Steps: actual +10 +15 +15 −10 −10; model +8 +12 +8 +6 −8: four of five the same way.
    assert s.direction == pytest.approx(0.8)
    assert (s.peak_actual, s.peak_model) == (40.0, 34.0)
    assert s.peak_lag == 1  # the model peaked a day later
    assert (s.end_model, s.end_actual) == (26.0, 20.0)
    # Missing values are left out, and nothing moving means no direction.
    gap = score(np.array([1.0, np.nan, 3.0]), np.array([1.0, 2.0, 2.0]))
    assert gap.n == 2
    assert score(np.array([1.0, 2.0]), np.array([5.0, 5.0])).direction is None
    with pytest.raises(ValueError, match="same dates"):
        score(np.zeros(3), np.zeros(4))
    # Weekly direction: a model right about each week's move, though not each day's.
    days = np.arange(15.0)
    noisy = days + np.where(np.arange(15) % 2, 0.8, -0.8)
    assert score(days, noisy, horizon=5).direction == 1.0
    daily = score(days, noisy).direction
    assert daily is not None
    assert daily < 1.0
    with pytest.raises(ValueError, match="horizon"):
        score(days, noisy, horizon=0)


def test_the_summary_says_what_went_right_and_wrong() -> None:
    actual = np.array([0.0, 10.0, 25.0, 40.0, 30.0, 20.0])
    lines = summarize("30Y", " bp", score(actual * 0.5, actual), digits=0)
    assert lines[0].startswith("30Y: direction mostly right, the same way as what happened")
    assert lines[0].endswith("in 100% of the days that moved")
    assert "peak move +20 bp against +40 bp, too small, on time" in lines[1]
    assert "ended +10 bp against +20 bp" in lines[2]
    late = summarize(
        "10Y", " bp", score(np.array([0.0, 5.0, 20.0, 45.0]), np.array([0.0, 40.0, 30.0, 35.0]))
    )
    assert "2 days late" in late[1]
    wrong = summarize("x", "", score(-actual, actual))
    assert "often wrong" in wrong[0]
    assert "the wrong way" in wrong[1]


def _gilt_like(seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    sales = rng.uniform(-6, 12, 18)  # £bn a day, net of purchases
    return 2.0 + 15.0 * sales / 12.0 + rng.normal(0, 1.5, 18), sales  # 15 bp per day's turnover


def test_lambda_recovers_a_known_impact() -> None:
    dy, sales = _gilt_like(2)
    fit = fit_lambda(dy, sales, depth=12.0, boots=1000, seed=3)
    assert fit.lam == pytest.approx(15.0, abs=1.5)
    assert fit.low < fit.lam < fit.high
    assert fit.low < 15.0 < fit.high
    assert (fit.n, fit.boots) == (18, 1000)
    assert 0.5 < fit.r2 <= 1.0
    # The same selling moves a market ten times deeper a tenth as much per £ sold.
    assert move_per_unit(fit.lam, 120.0) == pytest.approx(move_per_unit(fit.lam, 12.0) / 10)
    with pytest.raises(ValueError, match="varying net sales"):
        fit_lambda([1.0, 2.0, 3.0, 4.0], [1.0, 1.0, 1.0, 1.0], depth=12.0)


def test_the_bootstrap_interval_undercovers_a_little_with_few_days() -> None:
    """With 18 days the 90% percentile interval covers the true λ about 80% of the time (a
    known small-sample shortfall of the pairs bootstrap, recorded in ASSUMPTIONS.md)."""
    covered = 0
    for seed in range(60):
        dy, sales = _gilt_like(seed)
        fit = fit_lambda(dy, sales, depth=12.0, boots=300, seed=3)
        covered += fit.low < 15.0 < fit.high
    assert 0.7 <= covered / 60 <= 0.97


PARAMS = LinkParams(
    spillover=0.2, debt_flow=5.0, equity_flow=-4.0, risk_flow=-0.3, intervention=0.5, inr_per_bn=0.2
)
START = MarketStart(inr=60.0, reserves_bn=290.0, surplus_cr=0.0, ndtl_cr=8e6, repo=0.0725)


def test_one_days_move_replays_like_a_single_shock() -> None:
    days = 30
    us = np.zeros(days)
    us[0] = 12.0
    replay = replay_chain(us, np.zeros(days), START, PARAMS)
    single = run_chain(FedShock(0.0, 12.0), START, PARAMS, horizon_days=days)
    np.testing.assert_allclose(replay.fpi_bn, single.fpi_bn)
    np.testing.assert_allclose(replay.inr, single.inr)
    np.testing.assert_allclose(replay.reserves_bn, single.reserves_bn)
    assert replay.in10y_bp[-1] == pytest.approx(2.4)


def test_daily_moves_superpose() -> None:
    rng = np.random.default_rng(0)
    us, vix = rng.normal(0, 5, 60), rng.normal(0, 1, 60)
    both = replay_chain(us, vix, START, PARAMS)
    one = replay_chain(us, np.zeros(60), START, PARAMS)
    other = replay_chain(np.zeros(60), vix, START, PARAMS)
    np.testing.assert_allclose(both.fpi_bn, one.fpi_bn + other.fpi_bn)
    np.testing.assert_allclose(both.rbi_bn, 0.5 * both.fpi_bn)
    np.testing.assert_allclose(both.reserves_bn[-1], 290.0 + both.rbi_bn.sum())
    with pytest.raises(ValueError, match="one US 10Y change"):
        replay_chain(us, vix[:10], START, PARAMS)
