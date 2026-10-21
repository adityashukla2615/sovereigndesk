"""Price impact from a fire sale, calibrated on the 2022 gilt crisis.

A day's yield change is set against that day's net forced selling (forced sales less the
central bank's purchases) as a multiple of the market's normal daily turnover: λ is the move,
in basis points, for selling one normal day's turnover. It travels to another market through
that market's own turnover (the depth ratio), so the same λ moves a deep market less per
pound or dollar sold.
"""

from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, as_float_array


@dataclass(frozen=True, slots=True)
class LambdaFit:
    lam: float
    """Basis points per normal day's turnover sold, net."""
    alpha: float
    """The average daily move not explained by the selling (bp)."""
    low: float
    high: float
    """Bootstrap percentile interval for λ."""
    level: float
    n: int
    r2: float
    boots: int


def fit_lambda(
    dy_bp: ArrayLike,
    net_sales: ArrayLike,
    depth: float,
    *,
    boots: int = 2000,
    seed: int = 0,
    level: float = 0.90,
) -> LambdaFit:
    """λ by least squares of daily yield changes on net forced selling over depth, with a
    bootstrap interval (days resampled with replacement).

    Equation:
        Δyₜ = α + λ·xₜ + εₜ,   xₜ = (forced salesₜ − purchasesₜ) / depth;
        λ̂ = Σ(xₜ − x̄)(Δyₜ − Δȳ) / Σ(xₜ − x̄)²;   interval = percentiles of λ̂ over resamples
    """
    y, x = as_float_array(dy_bp), as_float_array(net_sales) / depth
    keep = np.isfinite(y) & np.isfinite(x)
    y, x = y[keep], x[keep]
    if y.size < 4 or np.ptp(x) == 0:
        raise ValueError("need at least four days with varying net sales")

    def ols(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float]:
        xc = xs - xs.mean()
        denom = float(xc @ xc)
        slope = float(xc @ (ys - ys.mean())) / denom if denom > 0 else float("nan")
        return slope, float(ys.mean() - slope * xs.mean())

    lam, alpha = ols(x, y)
    resid = y - alpha - lam * x
    centred = y - y.mean()
    r2 = 1 - float(resid @ resid) / float(centred @ centred) if centred @ centred > 0 else 0.0
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(boots):
        idx = rng.integers(0, y.size, y.size)
        slope, _ = ols(x[idx], y[idx])
        if np.isfinite(slope):
            draws.append(slope)
    tail = (1 - level) / 2 * 100
    low, high = (float(v) for v in np.percentile(draws, [tail, 100 - tail]))
    return LambdaFit(lam, alpha, low, high, level, int(y.size), r2, len(draws))


def move_per_unit(lam: float, depth: float) -> float:
    """Basis points per unit of currency sold in a day, in a market with this daily turnover.

    Equation:
        λ_unit = λ / depth
    """
    if depth <= 0:
        raise ValueError("depth must be positive")
    return lam / depth
