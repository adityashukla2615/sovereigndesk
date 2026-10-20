"""How a shock to one factor spreads across maturities: the loadings both curve models use.

A policy-rate surprise that is expected to fade at rate κ moves the τ-year yield by the
average expected change over τ years, the Vasicek B(τ)/τ loading: one at the front end,
falling with maturity. A term-premium shock does the opposite, rising from zero at the front
end; it is normalised to one at 10 years so its size reads as the 10-year move.
"""

import math

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


def expectations_loading(tenors: ArrayLike, kappa: float) -> FloatArray:
    """Share of a policy-rate surprise that reaches each maturity, if it fades at rate κ.

    Equation:
        A(τ; κ) = (1 − e^(−κτ)) / (κτ),   A(0) = 1
    """
    if kappa <= 0:
        raise ValueError("κ must be positive")
    t = as_float_array(tenors)
    x = kappa * t
    safe = np.where(x > 0, x, 1.0)
    return np.asarray(np.where(x > 0, -np.expm1(-safe) / safe, 1.0), dtype=np.float64)


def term_premium_loading(tenors: ArrayLike, scale: float, *, at: float = 10.0) -> FloatArray:
    """Term-premium loading by maturity, normalised to one at ``at`` years (10 by default).

    Equation:
        T(τ; s) = (1 − e^(−τ/s)) / (1 − e^(−τ*/s)),   τ* = 10
    """
    if scale <= 0 or at <= 0:
        raise ValueError("the scale and the normalising maturity must be positive")
    t = as_float_array(tenors)
    return np.asarray(-np.expm1(-t / scale) / -math.expm1(-at / scale), dtype=np.float64)
