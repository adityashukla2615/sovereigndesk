"""The US → India chain: signs, magnitudes, conservation, RBI's responses, and the HAC fit."""

import numpy as np
import pytest

from sovereign_engine.india.liquidity_map import LiquidityMap
from sovereign_engine.linkage import (
    RESPONSES,
    FedShock,
    LinkParams,
    MarketStart,
    Response,
    ols_hac,
    run_chain,
)

PARAMS = LinkParams(
    spillover=0.2,
    debt_flow=5.0,
    equity_flow=-4.0,
    risk_flow=-0.3,
    intervention=0.5,
    inr_per_bn=0.2,
)
START = MarketStart(inr=88.0, reserves_bn=700.0, surplus_cr=150_000.0, ndtl_cr=2.5e7, repo=0.055)
MAP = LiquidityMap(deficit=0.0025, surplus=-0.0045, midpoint=0.8, width=0.95)
HIKE = FedShock(fed_bp=50.0, us10y_bp=12.0)


def test_a_fed_hike_drains_rupee_liquidity_and_lifts_wacr() -> None:
    path = run_chain(HIKE, START, PARAMS, liquidity_map=MAP, tbill_slope_bp=-8.8)
    t = path.totals()
    assert t["differential_bp"] == pytest.approx(-9.6)  # India's 10Y follows by a fifth
    assert t["fpi_bn"] < 0  # money leaves
    assert t["rbi_bn"] == pytest.approx(0.5 * t["fpi_bn"])  # RBI sells half of it
    assert t["reserves_bn"] < 0
    assert t["inr_pct"] > 0  # the rupee weakens (more rupees per dollar)
    assert t["drain_cr"] < 0
    assert t["surplus_cr"] == pytest.approx(t["drain_cr"])  # no response: nothing offsets
    assert t["wacr_bp"] > 0
    assert t["tbill_bp"] > 0
    # By hand: F = 5·(−0.096) − 4·(0.12) = −0.96 bn; RBI sells 0.48 bn ≈ ₹4,230 cr at ₹88.
    assert t["fpi_bn"] == pytest.approx(-0.96)
    assert t["inr_pct"] == pytest.approx(0.2 * 0.48, rel=0.01)
    assert t["drain_cr"] == pytest.approx(-0.48 * 100 * 88.0, rel=0.002)
    assert path.check() == []


def test_the_chain_is_linear_in_the_shock() -> None:
    one = run_chain(HIKE, START, PARAMS).totals()
    two = run_chain(FedShock(100.0, 24.0), START, PARAMS).totals()
    for key in ("in10y_bp", "differential_bp", "fpi_bn", "rbi_bn", "market_bn"):
        assert two[key] == pytest.approx(2 * one[key])
    assert two["drain_cr"] == pytest.approx(2 * one["drain_cr"], rel=0.002)  # the rate moves too
    risk_off = run_chain(FedShock(0.0, 0.0, vix=10.0), START, PARAMS).totals()
    assert risk_off["fpi_bn"] == pytest.approx(-3.0)  # 10 VIX points × −0.3 bn


def test_a_cut_runs_the_chain_the_other_way() -> None:
    hike = run_chain(HIKE, START, PARAMS).totals()
    cut = run_chain(FedShock(-50.0, -12.0), START, PARAMS).totals()
    assert cut["fpi_bn"] == pytest.approx(-hike["fpi_bn"])
    assert cut["inr_pct"] < 0  # the rupee strengthens
    assert cut["drain_cr"] > 0  # RBI's dollar purchases inject rupees


def test_flows_arrive_front_loaded_within_the_month() -> None:
    w = PARAMS.profile()
    assert w.sum() == pytest.approx(1.0)
    assert w.size == 21
    assert np.all(np.diff(w) < 0)
    assert w[5] == pytest.approx(w[0] / 2)  # five-day half-life
    short = run_chain(HIKE, START, PARAMS, horizon_days=10).totals()
    assert short["fpi_bn"] == pytest.approx(-0.96 * w[:10].sum())


@pytest.mark.parametrize("response", RESPONSES)
def test_every_response_keeps_the_books(response: Response) -> None:
    path = run_chain(HIKE, START, PARAMS, response=response, liquidity_map=MAP)
    assert path.check() == []


def test_rbis_responses() -> None:
    def run(response: Response) -> dict[str, float]:
        return run_chain(HIKE, START, PARAMS, response=response, liquidity_map=MAP).totals()

    none, vrr, omo, swap, hike = (run(r) for r in RESPONSES)
    # VRR funds the drain so far each week, but RBI's net position (the map's x) is unchanged.
    path = run_chain(HIKE, START, PARAMS, response="vrr")
    auctions = np.flatnonzero(path.vrr_cr)
    assert auctions.tolist() == [1, 6, 11, 16, 21, 26]
    for day in auctions:
        assert path.vrr_cr[day] == pytest.approx(-path.drain_cr[:day].sum())
    assert vrr["surplus_cr"] == pytest.approx(none["surplus_cr"])
    assert vrr["wacr_bp"] == pytest.approx(none["wacr_bp"])
    assert vrr["vrr_cr"] > 0
    # Weekly OMOs offset all but the drain since the last purchase.
    assert abs(omo["surplus_cr"]) < abs(none["surplus_cr"]) / 5
    # A buy/sell swap buys back the dollars RBI sells, so reserves end where they began.
    assert swap["reserves_bn"] == pytest.approx(0.0, abs=1e-9)
    assert swap["surplus_cr"] > none["surplus_cr"]
    # A repo hike widens the differential again: less money leaves, but rates rise.
    assert none["fpi_bn"] < hike["fpi_bn"] < 0
    assert hike["repo_bp"] == 25.0
    assert hike["wacr_bp"] > none["wacr_bp"] + 20


def test_parameters_are_checked() -> None:
    with pytest.raises(ValueError, match="share between 0 and 1"):
        LinkParams(0.2, 5.0, -4.0, -0.3, 1.5, 0.2)
    with pytest.raises(ValueError, match="horizon_days"):
        run_chain(HIKE, START, PARAMS, horizon_days=0)


def test_a_broken_path_fails_its_check() -> None:
    path = run_chain(HIKE, START, PARAMS)
    path.drain_cr[3] += 1_000.0
    assert "rupee liquidity" in " ".join(path.check())


def test_ols_with_newey_west_errors() -> None:
    rng = np.random.default_rng(4)
    n = 400
    x = rng.normal(size=n)
    e = np.zeros(n)
    for t in range(1, n):  # autocorrelated errors
        e[t] = 0.6 * e[t - 1] + rng.normal(scale=0.5)
    y = 1.0 + 2.0 * x + e
    y[7] = np.nan  # dropped
    fit = ols_hac(y, {"x": x}, lags=6)
    assert fit.n == n - 1
    assert fit.value("const") == pytest.approx(1.0, abs=0.25)
    assert fit.value("x") == pytest.approx(2.0, abs=0.1)
    lo, hi = fit.interval("x")
    assert lo < 2.0 < hi
    assert 0.8 < fit.r2 < 1.0
    # Without lags the errors are White's: (XᵀX)⁻¹ Σ ûₜ² xₜxₜᵀ (XᵀX)⁻¹.
    white = ols_hac(y, {"x": x}, lags=0)
    keep = np.isfinite(y)
    design = np.column_stack([np.ones(keep.sum()), x[keep]])
    resid = y[keep] - design @ white.coef
    inv = np.linalg.inv(design.T @ design)
    cov = inv @ (design.T * resid**2) @ design @ inv
    np.testing.assert_allclose(white.se, np.sqrt(np.diag(cov)))
    with pytest.raises(ValueError, match="cannot identify"):
        ols_hac([1.0, 2.0], {"x": [1.0, 2.0]}, lags=0)
