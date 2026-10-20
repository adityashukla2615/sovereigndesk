"""The Hodrick–Prescott trend, and its one-sided version for real-time output gaps.

The two-sided filter uses future observations to place today's trend; at each date the
one-sided version filters only the data up to that date and keeps the last trend value, so a
gap computed from it was knowable at the time.
"""

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


def hp_trend(series: ArrayLike, lam: float = 1600.0) -> FloatArray:
    """Hodrick–Prescott trend (λ = 1600 for quarterly data).

    Equation:
        τ = argmin Σₜ (yₜ − τₜ)² + λ Σₜ (τₜ₊₁ − 2τₜ + τₜ₋₁)²   ⇔   (I + λ DᵀD) τ = y
    """
    y = as_float_array(series)
    n = y.size
    if y.ndim != 1 or n < 3:
        raise ValueError("need at least three observations")
    if lam < 0:
        raise ValueError("λ must be non-negative")
    d = np.zeros((n - 2, n))
    rows = np.arange(n - 2)
    d[rows, rows], d[rows, rows + 1], d[rows, rows + 2] = 1.0, -2.0, 1.0
    return np.asarray(np.linalg.solve(np.eye(n) + lam * d.T @ d, y), dtype=np.float64)


def hp_one_sided(series: ArrayLike, lam: float = 1600.0, *, min_obs: int = 8) -> FloatArray:
    """One-sided HP trend: at each date, the end point of the filter run on data up to it.

    Equation:
        τ̂ₜ = [HP(y₁, …, yₜ)]ₜ  for t ≥ m,   undefined (NaN) before   (m = ``min_obs``)
    """
    y = as_float_array(series)
    if min_obs < 3:
        raise ValueError("need at least three observations per filter run")
    out = np.full(y.shape, np.nan)
    for t in range(min_obs - 1, y.size):
        out[t] = hp_trend(y[: t + 1], lam)[-1]
    return out
