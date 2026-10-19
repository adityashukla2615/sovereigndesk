import math
from datetime import date

import numpy as np
import pytest

from sovereign_engine.us.balance_sheet import (
    AVERAGE_MONTH_DAYS,
    FedBalanceSheet,
    QTPlan,
    ten_year_equivalents,
    term_premium_effect,
)
from sovereign_engine.us.corridor import (
    FedCorridor,
    ReserveDemandCurve,
    effr_target,
    fit_reserve_demand,
)
from sovereign_engine.us.debt import (
    DebtPath,
    DebtSecurity,
    IssuanceMix,
    YieldPath,
    project_debt_service,
)
from sovereign_engine.us.impact import BUCKET_TENORS, PriceImpactModel, split_sale

# ----------------------------------------------------------------------- corridor

CORRIDOR = FedCorridor(lower=0.0375, upper=0.0400, iorb=0.0390, on_rrp=0.0375)


def test_corridor_shift_keeps_administered_offsets() -> None:
    hiked = CORRIDOR.shifted(0.0025)
    assert (hiked.lower, hiked.upper) == pytest.approx((0.0400, 0.0425))
    assert hiked.upper - hiked.iorb == pytest.approx(CORRIDOR.upper - CORRIDOR.iorb)
    assert hiked.on_rrp - hiked.lower == pytest.approx(CORRIDOR.on_rrp - CORRIDOR.lower)
    assert hiked.srf_rate == hiked.upper
    with pytest.raises(ValueError, match="lower ≤ ON RRP"):
        FedCorridor(lower=0.04, upper=0.0425, iorb=0.05, on_rrp=0.04)


CURVE = ReserveDemandCurve(abundant=-0.0007, scarce=0.0030, midpoint=0.08, width=0.012)


def test_reserve_demand_curve_shape() -> None:
    assert float(CURVE.spread(0.40)) == pytest.approx(CURVE.abundant, abs=1e-8)
    assert float(CURVE.spread(-1.0)) == pytest.approx(CURVE.scarce, abs=1e-12)  # far-left asymptote
    assert float(CURVE.spread(CURVE.midpoint)) == pytest.approx((CURVE.abundant + CURVE.scarce) / 2)
    ratios = np.linspace(0.02, 0.20, 50)
    assert np.all(np.diff(CURVE.spread(ratios)) < 0)  # scarcer reserves, higher spread
    h = 1e-6
    numeric = (CURVE.spread(0.09 + h) - CURVE.spread(0.09 - h)) / (2 * h)
    assert float(CURVE.slope(0.09)) == pytest.approx(float(numeric), rel=1e-6)


def test_effr_target_stays_in_the_range() -> None:
    abundant = effr_target(CORRIDOR, CURVE, 0.40)
    assert abundant == pytest.approx(CORRIDOR.iorb + CURVE.abundant, abs=1e-9)
    squeezed = effr_target(CORRIDOR, ReserveDemandCurve(-0.0007, 0.05, 0.08, 0.01), 0.01)
    assert squeezed == CORRIDOR.upper


def test_fit_recovers_a_known_curve() -> None:
    rng = np.random.default_rng(3)
    x = rng.uniform(0.05, 0.20, 300)
    y = CURVE.spread(x) + rng.normal(0, 0.5e-4, x.size)  # 0.5 bp noise
    fit = fit_reserve_demand(x, y)
    assert fit.rmse_bp < 0.6
    grid = np.linspace(0.05, 0.20, 30)
    assert np.max(np.abs(fit.curve.spread(grid) - CURVE.spread(grid))) < 0.4e-4


# ----------------------------------------------------------------------- balance sheet and QT

SHEET = FedBalanceSheet.from_h41(
    total_assets=6600, treasuries=4200, mbs=2100, reserves=3000, on_rrp=150, tga=850, currency=2400
)


def test_h41_residuals_make_the_identity_exact() -> None:
    assert SHEET.identity_gap() == pytest.approx(0.0, abs=1e-9)
    assert SHEET.other_assets == pytest.approx(300)


def test_runoff_drains_on_rrp_first_then_reserves() -> None:
    small = SHEET.run_off(60, 35)
    assert (small.on_rrp, small.reserves) == pytest.approx((55, 3000))
    big = SHEET.run_off(150, 50)
    assert (big.on_rrp, big.reserves) == pytest.approx((0, 2950))
    for sheet in (small, big):
        assert sheet.identity_gap() == pytest.approx(0.0, abs=1e-9)
        assert sheet.total_assets == pytest.approx(
            SHEET.total_assets - (SHEET.treasuries - sheet.treasuries) - (SHEET.mbs - sheet.mbs)
        )
    with pytest.raises(ValueError, match="non-negative"):
        SHEET.run_off(-1, 0)


def test_qt_plan() -> None:
    plan = QTPlan.from_total(95)
    assert (plan.treasury_cap, plan.mbs_cap) == pytest.approx((60, 35))
    assert plan.runoff(AVERAGE_MONTH_DAYS) == pytest.approx((60, 35))
    assert plan.runoff(1.0)[0] == pytest.approx(60 / AVERAGE_MONTH_DAYS)


def test_term_premium_elasticity_matches_feds_note() -> None:
    gdp = 31_000.0
    assert term_premium_effect(0.01 * gdp, gdp) == pytest.approx(0.0010)  # 1% of GDP → 10 bp
    assert ten_year_equivalents(100, duration=4.2, ten_year_duration=8.4) == pytest.approx(50)


# ----------------------------------------------------------------------- price impact

MODEL = PriceImpactModel(reference_market=8_600.0)
TENORS = np.array([2.0, 5.0, 10.0, 20.0, 30.0])


def _simulate_sale(
    model: PriceImpactModel, amount: float, days: int, after: int, market: float
) -> np.ndarray:
    """Sell evenly over ``days`` at the belly, then wait ``after`` days; Δy in bp by tenor."""
    temp = np.zeros_like(TENORS)
    sold = 0.0
    pace = amount / days
    for day in range(days + after):
        selling = day < days
        sold += pace if selling else 0.0
        target = model.temporary_target({"BELLY": pace if selling else 0.0}, market, TENORS)
        temp = model.relax(temp, target, 1.0)
    return np.asarray((model.permanent({"BELLY": sold}, market, TENORS) + temp) * 1e4)


def test_reproduces_beltran_et_al_calibration() -> None:
    """$100bn sold within a month: 5y +40–60 bp short run, about +20 bp in the long run."""
    month = round(AVERAGE_MONTH_DAYS)
    short_run = _simulate_sale(MODEL, 100, month, 0, MODEL.reference_market)
    long_run = _simulate_sale(MODEL, 100, month, 90, MODEL.reference_market)
    five_year = list(TENORS).index(5.0)
    assert 40 <= short_run[five_year] <= 60
    assert long_run[five_year] == pytest.approx(20, abs=0.05)
    assert np.all(long_run <= long_run[five_year] + 1e-9)  # the belly sale peaks at the belly


def test_impact_scales_inversely_with_market_size() -> None:
    small = MODEL.permanent({"LONG": 50}, 8_600, TENORS)
    large = MODEL.permanent({"LONG": 50}, 17_200, TENORS)
    assert np.allclose(large, small / 2)
    paced = MODEL.temporary_target({"SHORT": 4 * MODEL.reference_pace}, 8_600, TENORS)
    base = MODEL.temporary_target({"SHORT": MODEL.reference_pace}, 8_600, TENORS)
    assert np.allclose(paced, 2 * base)  # square-root law: 4× pace, 2× impact


def test_split_sale() -> None:
    assert split_sale(200, "LONG") == {"LONG": 200}
    assert split_sale(100, {"SHORT": 0.25, "LONG": 0.75}) == {"SHORT": 25, "LONG": 75}
    with pytest.raises(ValueError, match="buckets"):
        split_sale(100, {"ULTRA": 1.0})
    assert set(BUCKET_TENORS) == {"SHORT", "BELLY", "LONG"}


# ----------------------------------------------------------------------- debt service

START = date(2026, 11, 1)


def _flat(rate: float) -> YieldPath:
    return lambda month, tenor: rate


def test_single_bill_rolls_into_the_new_rate() -> None:
    ladder = [DebtSecurity("bill", date(2027, 1, 15), 0.04, 100.0, term=1.0)]
    path = project_debt_service(
        ladder, start=START, months=6, yield_at=_flat(0.05), mix=IssuanceMix((1.0,), (1.0,)),
        monthly_deficit=0.0, nominal_gdp=30_000, annual_receipts=5_000, nominal_growth=0.0,
    )  # fmt: skip
    assert np.allclose(path.interest, [4, 4, 5, 5, 5, 5])
    assert np.allclose(path.outstanding, 100)
    assert path.months[2] == date(2027, 1, 1)
    assert path.interest_to_gdp[0] == pytest.approx(4 / 30_000)


def test_deficits_and_higher_yields_raise_interest() -> None:
    ladder = [
        DebtSecurity("note", date(2028, 5, 15), 0.03, 500.0, term=5.0),
        DebtSecurity("tips", date(2030, 1, 15), 0.01, 100.0, term=10.0),
        DebtSecurity("frn", date(2027, 6, 30), 0.0, 50.0, term=2.0),
    ]
    mix = IssuanceMix((0.25, 2.0, 10.0), (0.3, 0.4, 0.3))

    def project(rate: float) -> DebtPath:
        return project_debt_service(
            ladder, start=START, months=48, yield_at=_flat(rate), mix=mix,
            monthly_deficit=10, nominal_gdp=30_000, annual_receipts=5_000,
        )  # fmt: skip

    low, high = project(0.04), project(0.06)
    assert low.outstanding[-1] == pytest.approx(650 + 48 * 10)
    assert np.all(high.interest >= low.interest)
    assert high.interest[-1] > low.interest[-1]
    # Month 0: notes 3%, TIPS 1% + 2.5% inflation, FRN at the 3-month yield + 10 bp, plus the
    # first month's deficit refinanced at the flat 4%.
    expected = 500 * 0.03 + 100 * 0.035 + 50 * 0.041 + 10 * 0.04
    assert low.interest[0] == pytest.approx(expected)
    assert math.isclose(low.average_rate[0], expected / 660)


def test_steady_state_mix_from_the_stock() -> None:
    mix = IssuanceMix.from_stock({0.25: 6_000, 2.0: 4_000, 10.0: 5_000})
    flows = {0.25: 24_000, 2.0: 2_000, 10.0: 500}  # stock / term
    total = sum(flows.values())
    assert mix.tenors == (0.25, 2.0, 10.0)
    assert mix.shares == pytest.approx(tuple(flows[t] / total for t in mix.tenors))
    with pytest.raises(ValueError, match="positive stock"):
        IssuanceMix.from_stock({1.0: 0.0})


def test_like_for_like_rollover_keeps_the_term() -> None:
    # A 2-year note maturing in month 1 is reissued as a 2-year note: it then stays outstanding
    # for 24 months at the new yield, even though the deficit mix is all bills.
    ladder = [DebtSecurity("note", date(2026, 12, 15), 0.02, 100.0, term=2.0)]
    path = project_debt_service(
        ladder, start=START, months=30, yield_at=lambda m, t: 0.05 if t >= 2 else 0.04,
        mix=IssuanceMix((0.25,), (1.0,)), monthly_deficit=0.0, nominal_gdp=30_000,
        annual_receipts=5_000, nominal_growth=0.0,
    )  # fmt: skip
    assert path.interest[0] == pytest.approx(2.0)
    assert np.allclose(path.interest[1:25], 5.0)  # reissued at the 2-year yield, not the bill yield
