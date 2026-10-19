import math

import numpy as np
import pytest

from sovereign_engine.bonds.approx import approx_price_change, price_yield_profile
from sovereign_engine.bonds.cashflows import (
    CashFlows,
    convexity,
    discount_factor,
    dv01,
    macaulay_duration,
    modified_duration,
    price,
    price_derivatives,
    risk_measures,
    yield_to_maturity,
)

# Hull, Options, Futures, and Other Derivatives, Table 4.6: a 3-year 10% bond with semiannual
# coupons, yield 12% continuously compounded.
HULL = CashFlows(times=np.arange(1, 7) / 2, amounts=np.array([5, 5, 5, 5, 5, 105.0]))


def test_hull_table_4_6() -> None:
    assert price(HULL, 0.12, None) == pytest.approx(94.213, abs=5e-4)
    assert macaulay_duration(HULL, 0.12, None) == pytest.approx(2.653, abs=5e-4)
    # Under continuous compounding modified duration equals Macaulay duration.
    assert modified_duration(HULL, 0.12, None) == pytest.approx(macaulay_duration(HULL, 0.12, None))
    direct = float(np.sum(HULL.amounts * HULL.times**2 * np.exp(-0.12 * HULL.times)))
    assert convexity(HULL, 0.12, None) == pytest.approx(direct / price(HULL, 0.12, None))


def test_rbi_primer_box_iv() -> None:
    # RBI, "Government Securities Market in India – A Primer", Box IV: 2-year 10% bond, yield 9%:
    # price 101.79, duration 3.73 half-years = 1.86 years, modified duration 1.78.
    bond = CashFlows.bullet(0.10, periods=4, freq=2)
    assert price(bond, 0.09, 2) == pytest.approx(101.79, abs=5e-3)
    assert macaulay_duration(bond, 0.09, 2) == pytest.approx(1.86, abs=5e-3)
    assert modified_duration(bond, 0.09, 2) == pytest.approx(1.78, abs=5e-3)


@pytest.mark.parametrize(
    ("coupon", "periods", "freq"), [(0.05, 20, 2), (0.0725, 60, 2), (0.03, 10, 1)]
)
def test_par_bond_identities(coupon: float, periods: int, freq: int) -> None:
    bond = CashFlows.bullet(coupon, periods, freq)
    assert price(bond, coupon, freq) == pytest.approx(100, abs=1e-10)
    # Modified duration of a par bond: (1 − (1 + y/f)^(−n)) / y.
    expected = (1 - (1 + coupon / freq) ** -periods) / coupon
    assert modified_duration(bond, coupon, freq) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("compounding", [1, 2, 12, None])
def test_zero_coupon_identities(compounding: int | None) -> None:
    maturity, y = 7.0, 0.043
    zero = CashFlows(times=np.array([maturity]), amounts=np.array([100.0]))
    assert macaulay_duration(zero, y, compounding) == pytest.approx(maturity)
    if compounding is None:
        assert modified_duration(zero, y, None) == pytest.approx(maturity)
        assert convexity(zero, y, None) == pytest.approx(maturity**2)
        assert price(zero, y, None) == pytest.approx(100 * math.exp(-y * maturity))
    else:
        g = 1 + y / compounding
        assert modified_duration(zero, y, compounding) == pytest.approx(maturity / g)
        expected = maturity * (maturity + 1 / compounding) / g**2
        assert convexity(zero, y, compounding) == pytest.approx(expected)


def test_dv01_and_risk_measures_agree() -> None:
    bond = CashFlows.bullet(0.04625, periods=20, freq=2)
    rm = risk_measures(bond, 0.0468, 2)
    assert rm.dv01 == pytest.approx(rm.modified_duration * rm.price * 1e-4)
    assert rm.dv01 == pytest.approx(dv01(bond, 0.0468, 2))
    assert rm.convexity == pytest.approx(convexity(bond, 0.0468, 2))
    assert rm.macaulay_duration == pytest.approx(rm.modified_duration * (1 + 0.0468 / 2))


def test_analytic_derivatives_match_finite_differences() -> None:
    bond = CashFlows.bullet(0.06, periods=30, freq=2, first_period=0.37)
    for compounding in (2, None):
        p, dp, d2p = price_derivatives(bond, 0.05, compounding)
        h = 1e-5
        up, down = price(bond, 0.05 + h, compounding), price(bond, 0.05 - h, compounding)
        assert dp == pytest.approx((up - down) / (2 * h), rel=1e-7)
        assert d2p == pytest.approx((up + down - 2 * p) / h**2, rel=1e-4)


@pytest.mark.parametrize(
    ("bond", "target"),
    [
        (CashFlows.bullet(0.05, 20, 2), 97.25),
        (CashFlows.bullet(0.08, 60, 2, first_period=0.2), 150.0),  # deep premium
        (CashFlows(np.array([30.0]), np.array([100.0])), 5.0),  # 30y zero at ~10.3%
        (CashFlows(np.array([1.0]), np.array([100.0])), 101.0),  # negative yield
    ],
)
def test_yield_round_trip(bond: CashFlows, target: float) -> None:
    for compounding in (2, None):
        y = yield_to_maturity(bond, target, compounding)
        assert price(bond, y, compounding) == pytest.approx(target, rel=1e-12)


def test_yield_rejects_impossible_inputs() -> None:
    bond = CashFlows.bullet(0.05, 4, 2)
    with pytest.raises(ValueError, match="positive price"):
        yield_to_maturity(bond, -1.0, 2)
    with pytest.raises(ValueError, match="domain"):
        discount_factor(1.0, -2.5, 2)


def test_cash_flow_validation() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        CashFlows(np.array([1.0, 1.0]), np.array([5.0, 105.0]))
    with pytest.raises(ValueError, match="equal length"):
        CashFlows(np.array([1.0]), np.array([5.0, 105.0]))
    with pytest.raises(ValueError, match="periods"):
        CashFlows.bullet(0.05, 0)


def test_price_yield_profile_and_taylor_error_order() -> None:
    bond = CashFlows.bullet(0.045, periods=20, freq=2)
    shifts = np.array([-0.02, -0.01, 0.0, 0.01, 0.02])
    profile = price_yield_profile(bond, 0.045, 2, shifts)
    assert profile.exact[2] == 0
    assert np.all(
        np.abs(profile.duration_convexity - profile.exact)
        <= np.abs(profile.duration_only - profile.exact)
    )
    # Third-order remainder: halving the shift cuts the second-order error about eightfold.
    d, c = modified_duration(bond, 0.045, 2), convexity(bond, 0.045, 2)
    p0 = price(bond, 0.045, 2)

    def error(h: float) -> float:
        return abs(price(bond, 0.045 + h, 2) / p0 - 1 - float(approx_price_change(d, c, h)))

    ratio = error(2e-3) / error(1e-3)
    assert 7.5 < ratio < 8.5
