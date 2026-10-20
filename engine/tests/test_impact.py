"""Module E: repricing (exact against its approximations), hold against sell, and the business
pass-through (signs, magnitudes, timing)."""

import numpy as np
import pytest

from sovereign_engine.impact import (
    BondHolding,
    BusinessProfile,
    FundHolding,
    LoanTerms,
    MarketMove,
    PassThrough,
    benchmark_path,
    bond_impact,
    business_impact,
    fit_benchmark,
    fund_impact,
    loan_rate_path,
    portfolio_impact,
    realised_yield,
)

TEN = BondHolding("10Y G-sec", face=500_000, coupon=0.07, years=10.0, yield0=0.07)
THIRTY = BondHolding("30Y G-sec", face=300_000, coupon=0.072, years=30.0, yield0=0.072)
FUND = FundHolding("Gilt fund", value=400_000, modified_duration=8.0, convexity=90.0)


def test_a_par_bond_reprices_exactly_and_the_approximations_bracket_it() -> None:
    up = bond_impact(TEN, 0.01)
    assert up.value0 == pytest.approx(500_000, rel=1e-9)  # a par bond is worth its face
    assert up.exact is not None
    assert up.exact < 0
    assert up.value1 == pytest.approx(up.value0 * (1 + up.exact))
    # Duration overstates the loss (convexity is positive); adding convexity brings it close.
    assert up.duration_only < up.exact
    assert abs(up.exact - up.duration_convexity) < abs(up.exact - up.duration_only) / 10
    # A textbook check: 7% semi-annual 10-year par bond, D ≈ 7.11, 100 bp up ≈ −6.8%.
    assert up.modified_duration == pytest.approx(7.106, abs=0.01)
    assert up.exact == pytest.approx(-0.0680, abs=0.0005)
    # DV01: a 1 bp rise costs about DV01.
    tiny = bond_impact(TEN, 0.0001)
    assert -tiny.change == pytest.approx(tiny.dv01, rel=1e-3)


def test_approximation_errors_shrink_with_the_order() -> None:
    errors = []
    for dy in (0.01, 0.005, 0.0025):
        h = bond_impact(THIRTY, dy)
        assert h.exact is not None
        errors.append((abs(h.exact - h.duration_only), abs(h.exact - h.duration_convexity)))
    # First order: error ∝ Δy² (quarters as Δy halves); second order: ∝ Δy³ (eighths).
    (a1, b1), (a2, b2), (a3, b3) = errors
    assert a1 / a2 == pytest.approx(4, rel=0.15)
    assert a2 / a3 == pytest.approx(4, rel=0.1)
    assert b1 / b2 == pytest.approx(8, rel=0.2)
    assert b2 / b3 == pytest.approx(8, rel=0.2)


def test_longer_bonds_lose_more_and_falls_gain_more_than_rises_lose() -> None:
    assert bond_impact(THIRTY, 0.01).change / THIRTY.face < bond_impact(TEN, 0.01).change / TEN.face
    up, down = bond_impact(THIRTY, 0.01), bond_impact(THIRTY, -0.01)
    assert down.change > -up.change > 0  # convexity


def test_hold_to_maturity_against_selling_now() -> None:
    held = bond_impact(TEN, 0.01).hold
    assert held is not None
    assert held.redemption == TEN.face
    assert held.coupons == pytest.approx(TEN.face * 0.07 * 10)  # twenty coupons of 3.5%
    assert len(held.schedule) == 20
    assert held.sale_gain < 0  # selling crystallises the loss
    assert held.sale_proceeds == pytest.approx(TEN.face + held.sale_gain)
    # Held, the bond earns its yield; reinvesting coupons at a higher yield adds to it.
    assert held.bought_yield == pytest.approx(0.07)
    assert held.realised_yield > held.bought_yield
    flat = bond_impact(TEN, 0.0).hold
    assert flat is not None
    assert flat.realised_yield == pytest.approx(0.07, abs=1e-12)
    cf = TEN.cash_flows()
    assert realised_yield(cf, 100.0, 0.05) < 0.07  # lower reinvestment rates cost


def test_a_fund_has_only_the_estimates() -> None:
    f = fund_impact(FUND, 0.01)
    assert f.exact is None
    assert f.hold is None
    assert f.duration_only == pytest.approx(-0.08)
    assert f.duration_convexity == pytest.approx(-0.08 + 0.5 * 90 * 1e-4)
    assert f.value1 == pytest.approx(400_000 * (1 - 0.0755))
    assert f.dv01 == pytest.approx(400_000 * 8 * 1e-4)


def test_portfolio_totals_and_weights() -> None:
    p = portfolio_impact([TEN, THIRTY], [FUND], [0.01, 0.005, 0.0075])
    assert len(p.holdings) == 3
    assert p.change == pytest.approx(sum(h.change for h in p.holdings))
    assert p.value0 == pytest.approx(sum(h.value0 for h in p.holdings))
    weights = np.array([h.value0 for h in p.holdings]) / p.value0
    assert p.modified_duration == pytest.approx(
        float(weights @ [h.modified_duration for h in p.holdings])
    )
    assert p.dv01 == pytest.approx(sum(h.dv01 for h in p.holdings))
    with pytest.raises(ValueError, match="one yield change per holding"):
        portfolio_impact([TEN], [FUND], [0.01])
    with pytest.raises(ValueError, match="empty"):
        portfolio_impact([], [], [])


SHOP = BusinessProfile(
    name="Small shop",
    monthly_sales=600_000,
    cost_share=0.82,
    import_share=0.05,
    fx_to_price=0.5,
    inventory_days=20,
    rate_semi_elasticity=-0.3,
    price_elasticity=-0.5,
    loan=LoanTerms(1_000_000, "EBLR", 0.035, reset_months=3, first_reset_month=1, tenor_months=12),
)
IMPORTER = BusinessProfile(
    name="Electronics importer",
    monthly_sales=15_000_000,
    cost_share=0.88,
    import_share=0.7,
    fx_to_price=0.6,
    inventory_days=60,
    rate_semi_elasticity=-2.0,
    price_elasticity=-1.2,
    loan=LoanTerms(
        20_000_000, "MCLR", 0.015, reset_months=12, first_reset_month=6, tenor_months=12
    ),
)
PT = PassThrough()
HIKE = MarketMove(repo=0.0025, money=0.0025, money_beta=1.0, inr_pct=0.0)


def test_an_eblr_loan_takes_a_repo_hike_at_its_reset() -> None:
    impact = business_impact(SHOP, HIKE, PT, base_benchmark=0.055, months=12)
    assert impact.base_rate == pytest.approx(0.09)
    np.testing.assert_allclose(impact.loan_rate, 0.0025)  # reset next month and every quarter
    assert impact.interest[0] == pytest.approx(1_000_000 * 0.0025 / 12)
    assert np.all(impact.volume_pct < 0)  # dearer credit, slightly fewer sales
    assert np.all(impact.margin < 0)
    late = LoanTerms(1_000_000, "EBLR", 0.035, reset_months=3, first_reset_month=3, tenor_months=12)
    rates = loan_rate_path(late, benchmark_path("EBLR", HIKE, PT, 12))
    np.testing.assert_allclose(rates[:2], 0.0)  # nothing until the first reset
    np.testing.assert_allclose(rates[2:], 0.0025)


def test_mclr_moves_partly_slowly_and_with_liquidity() -> None:
    path = benchmark_path("MCLR", HIKE, PT, 24)
    assert path[0] == 0.0  # a month's lag
    assert np.all(np.diff(path) >= 0)
    assert path[-1] == pytest.approx(0.61 * 0.0025, rel=0.05)  # most of the way after two years
    squeeze = benchmark_path("MCLR", MarketMove(0.0, 0.002, 1.0, 0.0), PT, 24)
    assert squeeze[-1] == pytest.approx(0.3 * 0.002, rel=0.05)  # a liquidity squeeze alone
    eblr = benchmark_path("EBLR", MarketMove(0.0, 0.002, 1.0, 0.0), PT, 12)
    np.testing.assert_allclose(eblr, 0.0)  # an external benchmark ignores it
    # An annual MCLR reset: the importer pays the old rate until month six.
    rates = loan_rate_path(IMPORTER.loan, path[:12])
    np.testing.assert_allclose(rates[:5], 0.0)
    assert rates[5] == pytest.approx(path[5])
    np.testing.assert_allclose(rates[5:], path[5])


def test_a_weaker_rupee_squeezes_an_importer() -> None:
    fall = MarketMove(repo=0.0, money=0.0, money_beta=1.0, inr_pct=5.0)
    impact = business_impact(IMPORTER, fall, PT, base_benchmark=0.0875, months=6)
    imported = 15_000_000 * 0.88 * 0.7
    # The old stock runs off over 60 days: half the move in the first month, all of it after.
    assert impact.import_cost[0] == pytest.approx(imported * 0.05 * 0.5)
    assert impact.import_cost[2] == pytest.approx(imported * 0.05)
    assert np.all(impact.price_pct > 0)
    assert np.all(impact.volume_pct < 0)
    assert np.all(impact.margin < 0)
    assert impact.interest == pytest.approx(np.zeros(6))  # no rate change
    # A shop that imports little barely notices.
    shop = business_impact(SHOP, fall, PT, base_benchmark=0.055, months=6)
    assert abs(shop.margin[-1]) < abs(impact.margin[-1]) / 50


def test_no_shock_no_impact() -> None:
    impact = business_impact(IMPORTER, MarketMove(0.0, 0.0, 1.0, 0.0), PT, base_benchmark=0.0875)
    for series in (impact.loan_rate, impact.interest, impact.sales, impact.margin):
        np.testing.assert_allclose(series, 0.0, atol=1e-9)
    assert impact.base_margin == pytest.approx(15_000_000 * 0.12 - 20_000_000 * 0.1025 / 12)


def test_profiles_are_checked() -> None:
    with pytest.raises(ValueError, match="share between 0 and 1"):
        BusinessProfile("x", 1.0, 1.2, 0.0, 0.0, 0.0, 0.0, 0.0, SHOP.loan)
    with pytest.raises(ValueError, match="reset_months"):
        LoanTerms(1.0, "EBLR", 0.0, reset_months=0, first_reset_month=0, tenor_months=1)


def test_benchmark_fit_recovers_share_and_speed() -> None:
    rng = np.random.default_rng(2)
    change_months = np.array([0.0, 1.0, 3.0, 5.0, 8.0, 10.0, 30.0, 32.0, 34.0])
    changes = np.array([0.004, 0.005, 0.005, 0.005, 0.0035, 0.0025, -0.0025, -0.0025, -0.005])
    months = np.arange(1.0, 52.0)
    elapsed = np.clip(months[:, None] - change_months[None, :], 0.0, None)
    truth = 0.074 + 0.6 * (changes * (1 - np.exp(-elapsed / 5.0))).sum(axis=1)
    observed = truth + rng.normal(0, 0.0002, months.size)
    fit = fit_benchmark(months, observed, change_months, changes)
    assert fit.share == pytest.approx(0.6, abs=0.05)
    assert fit.months == pytest.approx(5.0, rel=0.25)
    assert fit.level == pytest.approx(0.074, abs=0.002)
    assert fit.rmse < 0.0004
    assert fit.n == months.size
    with pytest.raises(ValueError, match="at least four"):
        fit_benchmark([1.0], [0.07], [0.0], [0.0025])
