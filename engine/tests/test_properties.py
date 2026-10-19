"""Property-based checks of the price–yield relationship (Hypothesis)."""

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from sovereign_engine.bonds.approx import approx_price_change
from sovereign_engine.bonds.cashflows import (
    CashFlows,
    Compounding,
    convexity,
    modified_duration,
    price,
    yield_to_maturity,
)

compounding_st = st.sampled_from([1, 2, 4, 12, None])


@st.composite
def bonds(draw: st.DrawFn) -> tuple[CashFlows, Compounding]:
    freq = draw(st.sampled_from([1, 2, 4]))
    periods = draw(st.integers(1, 80))
    coupon = draw(st.floats(0.0, 0.15))
    first = draw(st.floats(0.01, 1.0))
    return CashFlows.bullet(coupon, periods, freq, first_period=first), draw(compounding_st)


yields = st.floats(-0.01, 0.20)


def _third_derivative_bound(cf: CashFlows, y_low: float, compounding: Compounding) -> float:
    """max |P'''| on [y_low, ∞): |P'''| decreases in y, so it is attained at y_low."""
    t, c = cf.times, cf.amounts
    if compounding is None:
        return float(np.sum(c * t**3 * np.exp(-y_low * t)))
    m = compounding
    return float(np.sum(c * t * (t + 1 / m) * (t + 2 / m) * (1 + y_low / m) ** (-m * t - 3)))


@settings(max_examples=300, deadline=None)
@given(bonds(), yields, st.floats(1e-4, 0.05))
def test_price_strictly_decreasing_and_convex(
    bond: tuple[CashFlows, Compounding], y: float, gap: float
) -> None:
    cf, m = bond
    low, mid, high = price(cf, y, m), price(cf, y + gap / 2, m), price(cf, y + gap, m)
    assert low > mid > high
    assert mid <= (low + high) / 2 * (1 + 1e-12)


@settings(max_examples=300, deadline=None)
@given(bonds(), yields, st.floats(-0.02, 0.02))
def test_second_order_error_is_bounded_by_the_cubic_remainder(
    bond: tuple[CashFlows, Compounding], y: float, dy: float
) -> None:
    cf, m = bond
    p0 = price(cf, y, m)
    exact = price(cf, y + dy, m) / p0 - 1
    approx = float(approx_price_change(modified_duration(cf, y, m), convexity(cf, y, m), dy))
    remainder = _third_derivative_bound(cf, y - abs(dy), m) / (6 * p0) * abs(dy) ** 3
    assert abs(exact - approx) <= remainder * (1 + 1e-9) + 1e-13


@settings(max_examples=200, deadline=None)
@given(bonds(), yields)
def test_yield_round_trip(bond: tuple[CashFlows, Compounding], y: float) -> None:
    cf, m = bond
    target = price(cf, y, m)
    assert abs(yield_to_maturity(cf, target, m) - y) < 1e-9
