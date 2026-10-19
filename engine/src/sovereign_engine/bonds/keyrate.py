"""Pricing cash flows on a curve, and key-rate durations (Ho, 1992)."""

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array
from sovereign_engine.bonds.cashflows import CashFlows
from sovereign_engine.curves.base import Curve


def price_on_curve(cf: CashFlows, curve: Curve) -> float:
    """Present value of the cash flows discounted on a curve.

    Equation:
        P = Σᵢ CFᵢ · DF(tᵢ)
    """
    return float(cf.amounts @ curve.discount(cf.times))


def key_rate_weights(t: ArrayLike, key_tenors: ArrayLike) -> FloatArray:
    """Triangular bump profiles, one row per key tenor, that sum to one at every maturity.

    Equation:
        w_k(t) = 1 at K_k, falling linearly to 0 at K_{k−1} and K_{k+1};
        w_0 = 1 for t ≤ K_0 and w_last = 1 for t ≥ K_last;   Σ_k w_k(t) = 1
    """
    times, keys = as_float_array(t), as_float_array(key_tenors)
    if keys.ndim != 1 or keys.size == 0 or np.any(np.diff(keys) <= 0):
        raise ValueError("key tenors must be a strictly increasing 1-D array")
    eye = np.eye(keys.size)
    return np.vstack([np.interp(times, keys, eye[k]) for k in range(keys.size)])


def key_rate_durations(
    cf: CashFlows, curve: Curve, key_tenors: ArrayLike, bump: float = 1e-4
) -> FloatArray:
    """Sensitivity of price to a bump of the zero curve around each key tenor.

    Because the weights sum to one, the key-rate durations add up to the effective duration
    for a parallel shift of the continuously compounded zero curve.

    Equation:
        z_k^±(t) = z(t) ± h · w_k(t)
        KRD_k = −(P(z_k^+) − P(z_k^−)) / (2h · P(z))
    """
    t = cf.times
    zeros = curve.zero_rate(t)
    weights = key_rate_weights(t, key_tenors)
    base = float(cf.amounts @ np.exp(-zeros * t))
    up = np.exp(-(zeros + bump * weights) * t) @ cf.amounts
    down = np.exp(-(zeros - bump * weights) * t) @ cf.amounts
    return np.asarray(-(up - down) / (2 * bump * base), dtype=np.float64)
