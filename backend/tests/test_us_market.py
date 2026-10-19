"""The simulated US market: invariants under stress, QT plumbing, policy and sell-off effects."""

from dataclasses import replace

import numpy as np
import pytest

from app.sim.us_market import USMarket, USModelParams
from sovereign_engine.us.balance_sheet import QTPlan
from tests.support import make_us_anchors

QUIET = USModelParams(hw_sigma=0.0, tp_sigma=0.0, effr_rate_vol=1e-9)
"""Noise switched off, so deterministic effects can be measured exactly."""
MINUTE = 60 / (365.25 * 86400)
DAY = 1 / 365.25


def market(seed: int = 1, params: USModelParams | None = None, **overrides: object) -> USMarket:
    return USMarket(make_us_anchors(**overrides), np.random.default_rng(seed), params)


def test_opening_print_is_the_official_curve() -> None:
    m = market(params=QUIET)
    for tenor, value in m.par_curve().items():
        assert value == pytest.approx(m.anchors.par_curve[tenor], abs=1e-12)


def test_effr_never_leaves_the_range_over_10k_ticks() -> None:
    """Exit criterion of Phase 4: random hikes, cuts, QT and fire sales every few hundred ticks."""
    m = market(seed=7)
    rng = np.random.default_rng(99)
    for tick in range(10_000):
        if tick % 250 == 0:
            m.set_policy(float(rng.choice([-0.005, -0.0025, 0.0025, 0.005, 0.0075])))
        if tick % 1_000 == 0:
            m.set_qt(float(rng.uniform(0, 300)))
        if tick % 1_500 == 0 and m.state.holdings["Japan"] > 60:
            m.sell("Japan", 50, 0.5, str(rng.choice(["SHORT", "BELLY", "LONG"])))
        m.step(15 * MINUTE)
        m.check_invariants()
    assert m.state.corridor.lower <= m.state.effr <= m.state.corridor.upper


def test_effr_hugs_its_target_and_moves_with_a_hike() -> None:
    m = market(params=QUIET)
    for _ in range(7 * 24):  # a week in hour steps (the OU step is exact for any dt)
        m.step(DAY / 24)
    assert m.state.effr == pytest.approx(m.effr_target(), abs=1e-6)
    lower = m.state.corridor.lower
    m.set_policy(0.0025)
    assert m.state.corridor.lower == pytest.approx(lower + 0.0025)
    assert m.state.corridor.lower <= m.state.effr <= m.state.corridor.upper  # on the effective date


def test_qt_drains_on_rrp_first_then_reserves_and_keeps_the_identity() -> None:
    m = market(params=QUIET)
    rrp, reserves = m.state.sheet.on_rrp, m.state.sheet.reserves
    m.set_qt(95)
    m.step(10 * DAY)  # about $31bn of runoff: less than the $50bn in ON RRP
    assert m.state.sheet.on_rrp < rrp
    assert m.state.sheet.reserves == pytest.approx(reserves)
    for _ in range(60):
        m.step(DAY)
        m.check_invariants()
    assert m.state.sheet.on_rrp == pytest.approx(0, abs=1e-9)
    assert m.state.sheet.reserves < reserves
    assert m.qt_term_premium() > 0


def test_qt_halts_instead_of_overdrawing_reserves() -> None:
    m = market(params=replace(QUIET, reserves_floor=2_990.0))
    m.set_qt(500)
    notices: list[str] = []
    for _ in range(120):
        notices += m.step(DAY)
        m.check_invariants()
    assert m.state.qt_halted
    assert m.state.sheet.reserves == pytest.approx(2_990.0)
    assert any("QT halted" in n for n in notices)


def test_scarcer_reserves_lift_effr_relative_to_iorb() -> None:
    abundant = market(params=QUIET)
    scarce = market(params=QUIET)
    scarce.state.sheet = replace(
        scarce.state.sheet,
        reserves=1_800.0,
        other_liabilities=scarce.state.sheet.other_liabilities + 1_222.0,
    )
    assert scarce.effr_target() > abundant.effr_target()


def test_hike_moves_the_front_end_more_than_the_long_end() -> None:
    m = market(params=QUIET)
    before = m.par_curve()
    m.set_policy(0.0025)
    after = m.par_curve()
    moves = {k: after[k] - before[k] for k in after}
    assert moves["3M"] > moves["2Y"] > moves["10Y"] > moves["30Y"] > 0
    assert moves["3M"] == pytest.approx(0.0025, abs=2e-4)


def test_sell_off_raises_yields_where_it_lands_and_then_partly_retraces() -> None:
    m = market(params=QUIET)
    before = m.par_curve()
    m.sell("Japan", 200, 10, "LONG")
    held = m.state.holdings["Japan"]
    for _ in range(10):
        m.step(DAY)
    peak = m.par_curve()
    assert m.state.holdings["Japan"] == pytest.approx(held - 200)
    assert peak["30Y"] - before["30Y"] > peak["2Y"] - before["2Y"] > 0
    for _ in range(60):
        m.step(DAY)
    later = m.par_curve()
    assert 0 < later["30Y"] - before["30Y"] < peak["30Y"] - before["30Y"]  # temporary part decayed


def test_bigger_sales_move_yields_more() -> None:
    moves = []
    for amount in (50, 100, 200):
        m = market(params=QUIET)
        before = m.par_curve()["10Y"]
        m.sell("Japan", amount, 5, "BELLY")
        for _ in range(5):
            m.step(DAY)
        moves.append(m.par_curve()["10Y"] - before)
    assert moves[0] < moves[1] < moves[2]


def test_projection_matches_the_simulated_sale() -> None:
    m = market(params=QUIET, observed_qt=QTPlan(0.0, 0.0))
    before = m.par_curve()
    projection = m.project_sale(100, 10, "BELLY")
    m.sell("Japan", 100, 10, "BELLY")
    for _ in range(10 * 24):
        m.step(DAY / 24)
    simulated = m.par_curve()["10Y"] - before["10Y"]
    assert simulated == pytest.approx(projection["end_of_sale"]["10Y"], rel=1e-9)


def test_sales_cannot_exceed_holdings() -> None:
    m = market()
    m.sell("Japan", 1_000, 10, "BELLY")
    with pytest.raises(ValueError, match="not already being sold"):
        m.sell("Japan", 100, 10, "BELLY")
    with pytest.raises(ValueError, match="no TIC holdings"):
        m.sell("Atlantis", 1, 1, "BELLY")


def test_debt_service_rises_with_the_curve() -> None:
    m = market(params=QUIET)
    flat = m.debt_service(months=36)
    assert flat.shocked_interest == pytest.approx(flat.baseline_interest)
    m.set_policy(0.01)
    shocked = m.debt_service(months=36)
    assert all(
        s >= b for s, b in zip(shocked.shocked_interest, shocked.baseline_interest, strict=True)
    )
    assert shocked.delta_by_year["3"] > shocked.delta_by_year["1"] > 0


def test_qt_projection_paths() -> None:
    projection = market(params=QUIET).qt_projection(95)
    reserves = np.array(projection.reserves)
    assert len(reserves) == 24
    assert np.all(np.diff(reserves) <= 1e-9)
    assert np.all(np.diff(projection.effr_iorb_spread) >= -1e-12)
    assert (
        projection.ten_year_term_premium_change[-1] > projection.ten_year_term_premium_change[0] > 0
    )


def test_reanchor_keeps_shocks() -> None:
    m = market(params=QUIET)
    m.set_policy(0.005)
    m.sell("Japan", 100, 2, "LONG")
    for _ in range(3):
        m.step(DAY)
    before = m.par_curve()
    m.reanchor(make_us_anchors())
    after = m.par_curve()
    assert m.state.policy_shift == pytest.approx(0.005)
    assert m.state.sold["LONG"] == pytest.approx(100)
    for tenor in before:
        assert after[tenor] == pytest.approx(before[tenor], abs=1e-12)


def test_price_yield_panel() -> None:
    panel = market(params=QUIET).price_yield("10Y", [-100.0, 0.0, 100.0])
    assert panel.price == pytest.approx(100, abs=1e-9)  # a par bond at its own yield
    assert panel.exact[1] == 0
    assert panel.exact[0] > -panel.exact[2] > 0  # convexity: gains beat losses
    with pytest.raises(ValueError, match="coupon tenor"):
        market().price_yield("3M", [0.0])
