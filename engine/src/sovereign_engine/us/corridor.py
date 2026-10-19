"""The Fed's floor system: the target range, its administered rates, and the reserve-demand curve
that places the effective federal funds rate (EFFR) inside the range.

Afonso, Giannone, La Spada and Williams (2022, NY Fed Staff Report 1019) measure reserve demand
as the EFFR − IORB spread against reserves scaled by bank assets: flat once reserves exceed about
12–13% of bank assets, increasingly steep as they become scarce. A logistic curve has exactly
that shape; its parameters are fitted to real data (see ``fit_reserve_demand``).
"""

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


@dataclass(frozen=True, slots=True)
class FedCorridor:
    """Rates in decimals: target range [lower, upper], interest on reserve balances, ON RRP rate."""

    lower: float
    upper: float
    iorb: float
    on_rrp: float

    def __post_init__(self) -> None:
        if not self.lower < self.upper:
            raise ValueError("the target range needs lower < upper")
        if not self.lower - 1e-12 <= self.on_rrp <= self.iorb <= self.upper + 1e-12:
            raise ValueError("expected lower ≤ ON RRP ≤ IORB ≤ upper")

    @property
    def srf_rate(self) -> float:
        """Minimum bid rate of the standing repo facility: the top of the range."""
        return self.upper

    def shifted(self, change: float) -> "FedCorridor":
        """A hike (or cut) moves the range and keeps both administered-rate offsets.

        Equation:
            L' = L + Δ,  U' = U + Δ,  IORB' = U' − s₁,  RRP' = L' + s₂
            s₁ = U − IORB,  s₂ = RRP − L   (read from the latest data)
        """
        return FedCorridor(
            lower=self.lower + change,
            upper=self.upper + change,
            iorb=self.iorb + change,
            on_rrp=self.on_rrp + change,
        )

    def clamp(self, rate: ArrayLike) -> FloatArray:
        """Confine a rate to the target range.

        Equation:
            r ↦ min(max(r, L), U)
        """
        return np.clip(as_float_array(rate), self.lower, self.upper)


@dataclass(frozen=True, slots=True)
class ReserveDemandCurve:
    """EFFR − IORB spread (decimal) as a function of reserves / commercial-bank assets."""

    abundant: float
    """Spread when reserves are abundant (right asymptote)."""
    scarce: float
    """Spread as reserves become scarce (left asymptote)."""
    midpoint: float
    """Reserves-to-assets ratio half-way through the transition."""
    width: float
    """Ratio scale of the transition."""

    def __post_init__(self) -> None:
        if self.width <= 0 or self.scarce < self.abundant:
            raise ValueError("need width > 0 and scarce ≥ abundant")

    def spread(self, ratio: ArrayLike) -> FloatArray:
        """EFFR − IORB spread at a reserves-to-bank-assets ratio.

        Equation:
            s(x) = s_ab + (s_sc − s_ab) / (1 + e^((x − x₀)/w))
        """
        z = (as_float_array(ratio) - self.midpoint) / self.width
        return self.abundant + (self.scarce - self.abundant) / (1 + np.exp(np.clip(z, -60, 60)))

    def slope(self, ratio: ArrayLike) -> FloatArray:
        """Sensitivity of the spread to the reserves ratio (≤ 0; ≈ 0 when reserves are abundant).

        Equation:
            ds/dx = −(s_sc − s_ab)·e^z / (w·(1 + e^z)²),   z = (x − x₀)/w
        """
        z = np.clip((as_float_array(ratio) - self.midpoint) / self.width, -60, 60)
        ez = np.exp(z)
        return -(self.scarce - self.abundant) * ez / (self.width * (1 + ez) ** 2)


def effr_target(corridor: FedCorridor, curve: ReserveDemandCurve, reserves_ratio: float) -> float:
    """Where EFFR settles absent noise: IORB plus the reserve-demand spread, inside the range.

    Equation:
        EFFR* = clamp(IORB + s(R/A), L, U)
    """
    return float(corridor.clamp(corridor.iorb + float(curve.spread(reserves_ratio))))


@dataclass(frozen=True, slots=True)
class ReserveDemandFit:
    curve: ReserveDemandCurve
    rmse_bp: float
    n_points: int


def fit_reserve_demand(ratios: ArrayLike, spreads: ArrayLike) -> ReserveDemandFit:
    """Least-squares logistic fit of observed EFFR − IORB spreads on reserves / bank assets.

    Equation:
        min Σᵢ (s(xᵢ; θ) − sᵢ)²,  θ = (s_ab, s_sc − s_ab ≥ 0, x₀ ∈ [0.01, 0.30], w ∈ [0.002, 0.1])
        multi-start over x₀
    """
    x, y = as_float_array(ratios), as_float_array(spreads)
    if x.shape != y.shape or x.ndim != 1 or x.size < 8:
        raise ValueError("need at least eight (ratio, spread) points")

    def residuals_bp(p: FloatArray) -> FloatArray:
        ab, gap, mid, width = p
        return (ReserveDemandCurve(ab, ab + gap, mid, width).spread(x) - y) * 1e4

    lower = np.array([-0.01, 0.0, 0.01, 0.002])
    upper = np.array([0.01, 0.05, 0.30, 0.10])
    lo_spread = float(np.quantile(y, 0.1))
    hi_spread = float(np.quantile(y, 0.95))
    best = None
    for mid in (0.06, 0.08, 0.10, 0.12, 0.15):
        x0 = np.clip([lo_spread, max(hi_spread - lo_spread, 1e-4), mid, 0.01], lower, upper)
        sol = least_squares(residuals_bp, x0, bounds=(lower, upper), method="trf", x_scale="jac")
        sse = float(np.sum(sol.fun**2))
        if best is None or sse < best[0]:
            best = (sse, sol.x)
    if best is None:  # unreachable: the start list is non-empty
        raise RuntimeError("reserve-demand fit produced no candidate")
    ab, gap, mid, width = (float(v) for v in best[1])
    curve = ReserveDemandCurve(ab, ab + gap, mid, width)
    return ReserveDemandFit(curve, math.sqrt(best[0] / x.size), int(x.size))
