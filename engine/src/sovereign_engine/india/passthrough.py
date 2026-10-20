"""Repo pass-through to the G-sec curve, from an event study on RBI's repo changes.

On each day the repo rate changed, the move in each par yield from the previous publication to
that day's close is regressed on the repo change. Markets price most changes before the
meeting, so these same-day slopes are small. Dividing each by the 3-month slope gives the
response per unit of *policy surprise*: the 3-month yield's move measures the surprise and the
actual change instruments it (IV), so day-to-day noise in the 3-month yield does not bias the
ratio towards zero. The ratios are then fitted with two loadings: expectations (a surprise the
market expects to fade at rate κ, the Vasicek B(τ)/τ) and a term premium scaled by γ, the pair
normalised so the 3-month response is exactly one.

The events are few and the tenors' errors on one day are correlated, so the uncertainty comes
from resampling whole events (a bootstrap), not from per-tenor standard errors.
"""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import least_squares

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array
from sovereign_engine.rates.loadings import expectations_loading, term_premium_loading


def policy_changes(
    dates: Sequence[date], rates: ArrayLike, *, tol: float = 1e-6
) -> list[tuple[date, float]]:
    """The days on which a policy rate differs from its previous observation, with the change.

    Equation:
        events = {(tᵢ, rᵢ − rᵢ₋₁) : |rᵢ − rᵢ₋₁| > tol},   observations in date order
    """
    r = as_float_array(rates)
    if r.ndim != 1 or r.size != len(dates):
        raise ValueError("need one rate per date")
    if any(b <= a for a, b in itertools.pairwise(dates)):
        raise ValueError("dates must be strictly increasing")
    steps = np.diff(r)
    return [(dates[i + 1], float(s)) for i, s in enumerate(steps) if abs(s) > tol]


@dataclass(frozen=True, slots=True)
class EventStudy:
    tenors: FloatArray
    """Maturities in years, ascending."""
    changes: FloatArray
    """The repo change on each event day (decimal)."""
    responses: FloatArray
    """Par-yield change by event (rows) and tenor (columns), decimals."""
    day_beta: FloatArray
    """Same-day yield change per unit of repo change, by tenor."""
    relative: FloatArray
    """Response per unit of policy surprise: ``day_beta`` over the anchor tenor's."""
    relative_low: FloatArray
    relative_high: FloatArray
    """Bootstrap percentile band of ``relative`` at ``level`` (events resampled)."""
    relative_sd: FloatArray
    """Robust bootstrap s.d. of ``relative`` (interquartile range / 1.349)."""
    anchor: int
    """Index of the tenor whose move measures the surprise (its ratio is one)."""
    level: float
    draws: FloatArray
    """Bootstrap draws of ``relative`` (draw × tenor), reused for the fit's bands."""

    @property
    def anchor_tenor(self) -> float:
        return float(self.tenors[self.anchor])


def event_study(
    tenors: ArrayLike,
    changes: ArrayLike,
    responses: ArrayLike,
    *,
    anchor_tenor: float = 0.25,
    draws: int = 2000,
    level: float = 0.90,
    seed: int = 0,
) -> EventStudy:
    """Same-day pass-through by tenor, its ratio to the anchor tenor's (IV), and a bootstrap.

    A bootstrap draw whose anchor-tenor numerator is not positive leaves the ratio undefined
    and is dropped.

    Equation:
        b(τ) = Σₖ Δrₖ·Δyₖ(τ) / Σₖ Δrₖ²                       (OLS through the origin)
        ρ(τ) = b(τ) / b(τ₀) = Σₖ Δrₖ·Δyₖ(τ) / Σₖ Δrₖ·Δyₖ(τ₀)     (IV, τ₀ = 3 months)
        bands: percentiles of ρ over B resamples of the K events
    """
    t, dr, dy = as_float_array(tenors), as_float_array(changes), as_float_array(responses)
    if t.ndim != 1 or t.size < 2 or np.any(np.diff(t) <= 0):
        raise ValueError("need at least two ascending tenors")
    if dr.ndim != 1 or dr.size < 3 or dy.shape != (dr.size, t.size):
        raise ValueError("need at least three events, each with a response at every tenor")
    if np.any(dr == 0) or not np.all(np.isfinite(dy)):
        raise ValueError("every event needs a non-zero change and finite responses")
    if not 0 < level < 1 or draws < 100:
        raise ValueError("need 0 < level < 1 and at least 100 bootstrap draws")
    matches = np.flatnonzero(np.isclose(t, anchor_tenor))
    if matches.size != 1:
        raise ValueError("the anchor tenor must be one of the tenors")
    anchor = int(matches[0])
    cross = dr @ dy
    if cross[anchor] <= 0:
        raise ValueError(
            "the anchor tenor does not move with the repo rate on event days, "
            "so the surprise ratio is undefined"
        )
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, dr.size, size=(draws, dr.size))
    boot = np.einsum("bk,bkj->bj", dr[picks], dy[picks])
    usable = boot[:, anchor] > 0
    ratios = boot[usable] / boot[usable, anchor, None]
    low, high = np.percentile(ratios, [50 * (1 - level), 50 * (1 + level)], axis=0)
    q25, q75 = np.percentile(ratios, [25, 75], axis=0)
    return EventStudy(
        tenors=t,
        changes=dr,
        responses=dy,
        day_beta=cross / (dr @ dr),
        relative=cross / cross[anchor],
        relative_low=np.asarray(low, dtype=np.float64),
        relative_high=np.asarray(high, dtype=np.float64),
        relative_sd=np.asarray((q75 - q25) / 1.349, dtype=np.float64),
        anchor=anchor,
        level=level,
        draws=np.asarray(ratios, dtype=np.float64),
    )


@dataclass(frozen=True, slots=True)
class PassThrough:
    kappa: float
    """How fast the market expects a repo surprise to fade (per year)."""
    gamma: float
    """Term-premium response at 10 years per unit of surprise, before normalisation."""
    scale: float = 7.0
    """Maturity scale of the term-premium loading (years)."""
    anchor: float = 0.25
    """The tenor that moves one-for-one with the surprise (years)."""

    def __post_init__(self) -> None:
        if self.kappa <= 0 or self.scale <= 0 or self.anchor <= 0:
            raise ValueError("κ, the scale and the anchor tenor must be positive")

    def _norm(self) -> float:
        a = float(expectations_loading(self.anchor, self.kappa))
        return a + self.gamma * float(term_premium_loading(self.anchor, self.scale))

    def expectations(self, tenors: ArrayLike) -> FloatArray:
        """The part of the response that is the expected path of the repo rate.

        Equation:
            E(τ) = A(τ; κ) / N,   A(τ; κ) = (1 − e^(−κτ))/(κτ),   N = A(τ₀; κ) + γ·T(τ₀; s)
        """
        return expectations_loading(tenors, self.kappa) / self._norm()

    def term_premium(self, tenors: ArrayLike) -> FloatArray:
        """The part of the response that is a change in the term premium.

        Equation:
            P(τ) = γ·T(τ; s) / N,   T(τ; s) = (1 − e^(−τ/s)) / (1 − e^(−10/s))
        """
        return self.gamma * term_premium_loading(tenors, self.scale) / self._norm()

    def beta(self, tenors: ArrayLike) -> FloatArray:
        """Par-yield change at each maturity per unit of repo surprise; one at the anchor.

        Equation:
            β(τ) = (A(τ; κ) + γ·T(τ; s)) / (A(τ₀; κ) + γ·T(τ₀; s))
        """
        return np.asarray(self.expectations(tenors) + self.term_premium(tenors), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class PassThroughFit:
    curve: PassThrough
    rmse: float
    """Root-mean-square gap between the fitted β and the event-study ratios (fitted tenors)."""
    kappa_band: tuple[float, float]
    gamma_band: tuple[float, float]
    beta_10y_band: tuple[float, float]
    """Bootstrap bands at the study's level, from refitting each of ``band_draws`` draws."""
    band_draws: int

    @property
    def half_life_years(self) -> float:
        return float(np.log(2) / self.curve.kappa)


_KAPPA_BOUNDS = (0.005, 5.0)
_GAMMA_BOUNDS = (-1.0, 1.0)
_SD_FLOOR = 0.02


def fit_passthrough(
    study: EventStudy,
    *,
    scale: float = 7.0,
    band_draws: int = 200,
    seed: int = 1,
) -> PassThroughFit:
    """Fit the expectations and term-premium loadings to the event study's surprise ratios.

    Weights are the inverse squared bootstrap s.d. (floored at 0.02); the anchor tenor is left
    out, being one by construction.

    Equation:
        min_{κ, γ} Σ_{τ ≠ τ₀} w(τ)·(ρ(τ) − β(τ; κ, γ))²,   w(τ) = 1 / max(sd(τ), 0.02)²
        β(τ; κ, γ) = (A(τ; κ) + γ·T(τ; s)) / (A(τ₀; κ) + γ·T(τ₀; s)),   0 < κ ≤ 5,  |γ| ≤ 1
        bands: the same fit on bootstrap draws of ρ
    """
    keep = np.arange(study.tenors.size) != study.anchor
    t = study.tenors[keep]
    sqrt_w = 1 / np.maximum(study.relative_sd[keep], _SD_FLOOR)
    anchor = study.anchor_tenor
    lower = np.array([_KAPPA_BOUNDS[0], _GAMMA_BOUNDS[0]])
    upper = np.array([_KAPPA_BOUNDS[1], _GAMMA_BOUNDS[1]])

    def solve(target: FloatArray, starts: Sequence[tuple[float, float]]) -> tuple[float, float]:
        def residuals(p: FloatArray) -> FloatArray:
            curve = PassThrough(float(p[0]), float(p[1]), scale, anchor)
            return np.asarray((curve.beta(t) - target) * sqrt_w, dtype=np.float64)

        best: tuple[float, FloatArray] | None = None
        for start in starts:
            sol = least_squares(residuals, np.clip(start, lower, upper), bounds=(lower, upper))
            cost = float(np.sum(sol.fun**2))
            if best is None or cost < best[0]:
                best = (cost, np.asarray(sol.x, dtype=np.float64))
        if best is None:  # unreachable: starts is never empty
            raise ValueError("no starting values")
        return float(best[1][0]), float(best[1][1])

    kappa, gamma = solve(
        study.relative[keep], [(k, g) for k in (0.03, 0.15, 0.6, 2.0) for g in (-0.3, 0.0, 0.3)]
    )
    curve = PassThrough(kappa, gamma, scale, anchor)
    rmse = float(np.sqrt(np.mean((curve.beta(t) - study.relative[keep]) ** 2)))

    rng = np.random.default_rng(seed)
    available = study.draws.shape[0]
    rows = rng.choice(available, size=min(band_draws, available), replace=False)
    fits = [solve(study.draws[r, keep], [(kappa, gamma)]) for r in rows]
    kappas = np.array([k for k, _ in fits])
    gammas = np.array([g for _, g in fits])
    tens = np.array([float(PassThrough(k, g, scale, anchor).beta(10.0)) for k, g in fits])
    q = [50 * (1 - study.level), 50 * (1 + study.level)]

    def band(values: FloatArray) -> tuple[float, float]:
        lo, hi = np.percentile(values, q)
        return float(lo), float(hi)

    return PassThroughFit(
        curve=curve,
        rmse=rmse,
        kappa_band=band(kappas),
        gamma_band=band(gammas),
        beta_10y_band=band(tens),
        band_draws=len(fits),
    )
