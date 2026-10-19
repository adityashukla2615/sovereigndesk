"""Price, yield and risk of a stream of fixed cash flows at times measured in years.

This is the convention-free core. ``compounding`` is the number of compounding periods per
year ``m`` (2 for semiannual bond-equivalent yields), or ``None`` for continuous compounding.
Yields are decimals (0.05 = 5%); prices are per 100 face when the cash flows are.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array

Compounding = int | None
"""Compounding periods per year, or ``None`` for continuous compounding."""


@dataclass(frozen=True, slots=True)
class CashFlows:
    """Amounts paid at strictly increasing positive times (years from settlement)."""

    times: FloatArray
    amounts: FloatArray

    def __post_init__(self) -> None:
        times, amounts = as_float_array(self.times), as_float_array(self.amounts)
        if times.ndim != 1 or times.shape != amounts.shape or times.size == 0:
            raise ValueError("times and amounts must be non-empty 1-D arrays of equal length")
        if not (np.all(np.isfinite(times)) and np.all(np.isfinite(amounts))):
            raise ValueError("times and amounts must be finite")
        if times[0] <= 0 or np.any(np.diff(times) <= 0):
            raise ValueError("times must be positive and strictly increasing")
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "amounts", amounts)

    @classmethod
    def bullet(
        cls,
        coupon: float,
        periods: int,
        freq: int = 2,
        *,
        first_period: float = 1.0,
        redemption: float = 100.0,
    ) -> "CashFlows":
        """A fixed-coupon bullet bond: ``periods`` coupons, the first ``first_period`` away.

        Equation:
            t_k = (w + k) / f,   CF_k = R·c / f,   CF_{n−1} += R,   k = 0, …, n − 1
            (w = first_period, the fraction of a coupon period to the next payment)
        """
        if periods < 1 or not 0 < first_period <= 1:
            raise ValueError("need periods ≥ 1 and 0 < first_period ≤ 1")
        k = np.arange(periods, dtype=np.float64)
        amounts = np.full(periods, redemption * coupon / freq)
        amounts[-1] += redemption
        return cls(times=(first_period + k) / freq, amounts=amounts)


def _check_yield(y: float, compounding: Compounding) -> None:
    if compounding is not None and 1 + y / compounding <= 0:
        raise ValueError(f"yield {y} is outside the domain 1 + y/m > 0 for m = {compounding}")


def discount_factor(t: ArrayLike, y: float, compounding: Compounding) -> FloatArray:
    """Discount factor at yield ``y``.

    Equation:
        DF(t) = (1 + y/m)^(−m·t)        discrete compounding, m periods per year
        DF(t) = e^(−y·t)                continuous compounding
    """
    times = as_float_array(t)
    if compounding is None:
        return np.exp(-y * times)
    _check_yield(y, compounding)
    return np.exp(-compounding * times * math.log1p(y / compounding))


def price(cf: CashFlows, y: float, compounding: Compounding) -> float:
    """Present value of the cash flows at yield ``y``.

    Equation:
        P(y) = Σ_i CF_i · DF(t_i; y)
    """
    return float(cf.amounts @ discount_factor(cf.times, y, compounding))


def price_derivatives(
    cf: CashFlows, y: float, compounding: Compounding
) -> tuple[float, float, float]:
    """Price and its first two yield derivatives, analytically.

    Equation:
        dP/dy   = −Σ_i CF_i · t_i · (1 + y/m)^(−m·t_i − 1)
        d²P/dy² =  Σ_i CF_i · t_i · (t_i + 1/m) · (1 + y/m)^(−m·t_i − 2)
        continuous:  dP/dy = −Σ_i CF_i·t_i·e^(−y·t_i),   d²P/dy² = Σ_i CF_i·t_i²·e^(−y·t_i)
    """
    t, pv = cf.times, cf.amounts * discount_factor(cf.times, y, compounding)
    if compounding is None:
        return float(pv.sum()), float(-(t * pv).sum()), float((t * t * pv).sum())
    g = 1 + y / compounding
    first = -(t * pv).sum() / g
    second = (t * (t + 1 / compounding) * pv).sum() / (g * g)
    return float(pv.sum()), float(first), float(second)


def yield_to_maturity(
    cf: CashFlows,
    target_price: float,
    compounding: Compounding,
    *,
    guess: float = 0.05,
    tol: float = 1e-12,
    max_iter: int = 50,
) -> float:
    """The yield at which the cash flows are worth ``target_price``.

    P(y) is strictly decreasing and convex for positive cash flows, so Newton's method converges
    monotonically once it is left of the root; Brent's method on a bracket takes over if an
    iterate leaves the domain or fails to converge.

    Equation:
        solve P(y) = P*:   y_{n+1} = y_n − (P(y_n) − P*) / P'(y_n)
        fallback:          Brent root of P(y) − P* on [y_lo, y_hi] with P(y_lo) > P* > P(y_hi)
    """
    if target_price <= 0 or np.any(cf.amounts < 0) or not np.any(cf.amounts > 0):
        raise ValueError("need a positive price and non-negative, not all zero, cash flows")
    floor = -math.inf if compounding is None else -compounding * (1 - 1e-9)
    y = guess
    for _ in range(max_iter):
        p, dp, _ = price_derivatives(cf, y, compounding)
        if dp == 0:
            break
        step = (p - target_price) / dp
        y_next = y - step
        if not floor < y_next < 10.0:
            break
        y = y_next
        if abs(step) < tol:
            return y
    return _brent_yield(cf, target_price, compounding, floor)


def _brent_yield(cf: CashFlows, target: float, compounding: Compounding, floor: float) -> float:
    return _solve_decreasing(lambda y: price(cf, y, compounding), target, floor)


def _solve_decreasing(fn: Callable[[float], float], target: float, floor: float) -> float:
    """Root of fn(y) = target for fn strictly decreasing on (floor, ∞), by bracketing + Brent."""

    def excess(y: float) -> float:
        return fn(y) - target

    lo, hi = -0.05, 0.25
    while excess(lo) < 0:
        lo = max((lo + floor) / 2, lo - 1.0) if math.isfinite(floor) else lo - 1.0
        if lo - floor < 1e-12:
            raise ValueError("price too high: no yield in the domain reprices the cash flows")
    while excess(hi) > 0:
        hi *= 2
        if hi > 1e6:
            raise ValueError("price too low: no finite yield reprices the cash flows")
    return float(brentq(excess, lo, hi, xtol=1e-15, rtol=1e-15, maxiter=500))


def macaulay_duration(cf: CashFlows, y: float, compounding: Compounding) -> float:
    """Present-value-weighted average time to the cash flows, in years.

    Equation:
        D_mac = Σ_i t_i · CF_i · DF(t_i) / P
    """
    pv = cf.amounts * discount_factor(cf.times, y, compounding)
    return float((cf.times * pv).sum() / pv.sum())


def modified_duration(cf: CashFlows, y: float, compounding: Compounding) -> float:
    """Relative price sensitivity to the yield.

    Equation:
        D_mod = −(1/P)·dP/dy = D_mac / (1 + y/m);   continuous: D_mod = D_mac
    """
    p, dp, _ = price_derivatives(cf, y, compounding)
    return -dp / p


def convexity(cf: CashFlows, y: float, compounding: Compounding) -> float:
    """Second-order relative price sensitivity to the yield.

    Equation:
        C = (1/P)·d²P/dy²
    """
    p, _, d2p = price_derivatives(cf, y, compounding)
    return d2p / p


def dv01(cf: CashFlows, y: float, compounding: Compounding) -> float:
    """Price gain for a one-basis-point fall in yield (per the cash flows' face, usually 100).

    Equation:
        DV01 = −dP/dy × 0.0001 = D_mod · P × 0.0001
    """
    _, dp, _ = price_derivatives(cf, y, compounding)
    return -dp * 1e-4


@dataclass(frozen=True, slots=True)
class RiskMeasures:
    price: float
    macaulay_duration: float
    modified_duration: float
    convexity: float
    dv01: float


def risk_measures(cf: CashFlows, y: float, compounding: Compounding) -> RiskMeasures:
    """Price, durations, convexity and DV01 from one pass over the cash flows.

    Equation:
        P, D_mac, D_mod = −P'/P, C = P''/P, DV01 = −P' × 10⁻⁴   (see the single-measure functions)
    """
    p, dp, d2p = price_derivatives(cf, y, compounding)
    return RiskMeasures(
        price=p,
        macaulay_duration=macaulay_duration(cf, y, compounding),
        modified_duration=-dp / p,
        convexity=d2p / p,
        dv01=-dp * 1e-4,
    )
