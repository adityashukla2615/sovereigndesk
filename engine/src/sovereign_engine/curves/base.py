"""The curve interface every term structure implements, plus functions written against it.

Rates on a curve are continuously compounded decimals; times are years.
"""

import math
from typing import Protocol

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray


class Curve(Protocol):
    """A discount curve: discount factors, zero rates and instantaneous forwards."""

    def discount(self, t: ArrayLike) -> FloatArray: ...

    def zero_rate(self, t: ArrayLike) -> FloatArray: ...

    def forward_rate(self, t: ArrayLike) -> FloatArray: ...


def par_yield(curve: Curve, maturity: float, freq: int = 2) -> float:
    """Coupon rate at which a bond paying ``freq`` times a year prices at par on the curve.

    Equation:
        n = f·T coupon periods (T a whole number of periods)
        y_par(T) = f · (1 − DF(T)) / Σ_{k=1}^{n} DF(k/f)
    """
    periods = round(maturity * freq)
    if periods < 1 or not math.isclose(periods / freq, maturity, abs_tol=1e-9):
        raise ValueError("maturity must be a positive whole number of coupon periods")
    times = np.arange(1, periods + 1, dtype=np.float64) / freq
    dfs = curve.discount(times)
    return float(freq * (1 - dfs[-1]) / dfs.sum())


def forward_between(curve: Curve, t1: float, t2: float) -> float:
    """Continuously compounded forward rate between two times.

    Equation:
        F(t₁, t₂) = ln(DF(t₁) / DF(t₂)) / (t₂ − t₁)
    """
    if not 0 <= t1 < t2:
        raise ValueError("need 0 ≤ t1 < t2")
    d1, d2 = curve.discount(np.array([t1, t2]))
    return float(math.log(d1 / d2) / (t2 - t1))
