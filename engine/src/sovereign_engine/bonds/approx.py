"""Duration and convexity approximations of a yield move, next to exact repricing.

This is what the PY panel's yield slider draws: the exact price change and the two Taylor
approximations, whose gap is the error term O(Δy³).
"""

from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array
from sovereign_engine.bonds.cashflows import (
    CashFlows,
    Compounding,
    convexity,
    discount_factor,
    modified_duration,
    price,
)


def approx_price_change(modified_dur: float, convex: float, dy: ArrayLike) -> FloatArray:
    """Second-order Taylor approximation of the relative price change.

    Equation:
        ΔP/P ≈ −D_mod·Δy + ½·C·Δy²
    """
    shifts = as_float_array(dy)
    return -modified_dur * shifts + 0.5 * convex * shifts * shifts


@dataclass(frozen=True, slots=True)
class PriceYieldProfile:
    yields: FloatArray
    prices: FloatArray
    exact: FloatArray
    """Exact relative price change P(y₀ + Δy)/P(y₀) − 1."""
    duration_only: FloatArray
    """First-order approximation −D_mod·Δy."""
    duration_convexity: FloatArray
    """Second-order approximation −D_mod·Δy + ½·C·Δy²."""


def price_yield_profile(
    cf: CashFlows, y0: float, compounding: Compounding, shifts: ArrayLike
) -> PriceYieldProfile:
    """Exact repricing across yield shifts, with the duration and duration+convexity overlays.

    Equation:
        exact:      ΔP/P = P(y₀ + Δy)/P(y₀) − 1
        first:      ΔP/P ≈ −D_mod·Δy
        second:     ΔP/P ≈ −D_mod·Δy + ½·C·Δy²
    """
    dy = as_float_array(shifts)
    yields = y0 + dy
    p0 = price(cf, y0, compounding)
    prices = np.array([cf.amounts @ discount_factor(cf.times, y, compounding) for y in yields])
    d_mod, conv = modified_duration(cf, y0, compounding), convexity(cf, y0, compounding)
    return PriceYieldProfile(
        yields=yields,
        prices=prices,
        exact=prices / p0 - 1,
        duration_only=-d_mod * dy,
        duration_convexity=approx_price_change(d_mod, conv, dy),
    )
