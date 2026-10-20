"""The macro map of India's call money market: WACR − repo as a function of system liquidity.

When banks hold surplus reserves beyond the CRR (RBI absorbing on net through the SDF and
reverse repos), lenders compete and the weighted average call rate (WACR) sinks toward the SDF
rate; in deficit it rises toward the MSF rate. A logistic curve in surplus as a share of NDTL
has that shape; its parameters are fitted to RBI's daily Money Market Operations history.
"""

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


@dataclass(frozen=True, slots=True)
class LiquidityMap:
    """WACR − repo (decimal) against system surplus in per cent of NDTL."""

    deficit: float
    """Spread when liquidity is short (left asymptote)."""
    surplus: float
    """Spread when liquidity is ample (right asymptote)."""
    midpoint: float
    """Surplus (% of NDTL) half-way through the transition."""
    width: float
    """Surplus scale (% of NDTL) of the transition."""

    def __post_init__(self) -> None:
        if self.width <= 0 or self.deficit < self.surplus:
            raise ValueError("need width > 0 and deficit spread ≥ surplus spread")

    def spread(self, surplus_pct: ArrayLike) -> FloatArray:
        """WACR − repo at a system surplus of ``surplus_pct`` per cent of NDTL.

        Equation:
            s(ℓ) = s_d + (s_s − s_d) / (1 + e^(−(ℓ − m)/w))
        """
        z = np.clip((as_float_array(surplus_pct) - self.midpoint) / self.width, -60, 60)
        return self.deficit + (self.surplus - self.deficit) / (1 + np.exp(-z))

    def slope(self, surplus_pct: ArrayLike) -> FloatArray:
        """Sensitivity of the spread to surplus (≤ 0): how much WACR falls per point of NDTL.

        Equation:
            ds/dℓ = (s_s − s_d)·e^(−z) / (w·(1 + e^(−z))²),   z = (ℓ − m)/w
        """
        z = np.clip((as_float_array(surplus_pct) - self.midpoint) / self.width, -60, 60)
        ez = np.exp(-z)
        return (self.surplus - self.deficit) * ez / (self.width * (1 + ez) ** 2)


@dataclass(frozen=True, slots=True)
class LiquidityMapFit:
    curve: LiquidityMap
    rmse_bp: float
    n_points: int
    residual_ar1: float
    """Day-to-day autocorrelation of the fit residuals (persistence of WACR's deviations)."""


def fit_liquidity_map(surplus_pct: ArrayLike, spreads: ArrayLike) -> LiquidityMapFit:
    """Least-squares logistic fit of observed WACR − repo on surplus / NDTL, in date order.

    Equation:
        min Σᵢ (s(ℓᵢ; θ) − yᵢ)²,  θ = (s_d, s_d − s_s ≥ 0, m ∈ [−3, 3], w ∈ [0.05, 3])
        multi-start over m;  ρ = corr(eᵢ, eᵢ₋₁) of the residuals eᵢ
    """
    x, y = as_float_array(surplus_pct), as_float_array(spreads)
    if x.shape != y.shape or x.ndim != 1 or x.size < 8:
        raise ValueError("need at least eight (surplus, spread) points")

    def residuals_bp(p: FloatArray) -> FloatArray:
        deficit, gap, mid, width = p
        return (LiquidityMap(deficit, deficit - gap, mid, width).spread(x) - y) * 1e4

    lower = np.array([-0.01, 0.0, -3.0, 0.05])
    upper = np.array([0.03, 0.05, 3.0, 3.0])
    hi = float(np.quantile(y, 0.9))
    lo = float(np.quantile(y, 0.1))
    best = None
    for mid in (-0.5, 0.0, 0.5, 1.0, 1.5):
        x0 = np.clip([hi, max(hi - lo, 1e-4), mid, 0.5], lower, upper)
        sol = least_squares(residuals_bp, x0, bounds=(lower, upper), method="trf", x_scale="jac")
        sse = float(np.sum(sol.fun**2))
        if best is None or sse < best[0]:
            best = (sse, sol.x, sol.fun)
    if best is None:  # unreachable: the start list is non-empty
        raise RuntimeError("liquidity-map fit produced no candidate")
    deficit, gap, mid, width = (float(v) for v in best[1])
    resid = best[2]
    rho = float(np.corrcoef(resid[1:], resid[:-1])[0, 1]) if resid.size > 2 else 0.0
    return LiquidityMapFit(
        LiquidityMap(deficit, deficit - gap, mid, width),
        math.sqrt(best[0] / x.size),
        int(x.size),
        rho if math.isfinite(rho) else 0.0,
    )
