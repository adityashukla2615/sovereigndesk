"""Nelson–Siegel–Svensson curve, in the parameterisation of Gürkaynak, Sack and Wright (2007).

The Fed's daily GSW dataset (feds200628) publishes β₀…β₃, τ₁, τ₂ in this form; zero yields are
continuously compounded. Here rates are decimals, so the published percent β's divide by 100.

Fitting is two-stage: for fixed (τ₁, τ₂) the zero curve is linear in β, so a grid of (τ₁, τ₂)
pairs is scanned with bound-constrained linear least squares, then the best few seeds are
polished by bounded nonlinear least squares over all six parameters.
"""

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares, lsq_linear

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


def _level_and_hump(t: FloatArray, tau: float) -> tuple[FloatArray, FloatArray]:
    x = t / tau
    safe = np.where(x > 0, x, 1.0)
    level = np.where(x > 0, -np.expm1(-safe) / safe, 1.0)
    return level, level - np.exp(-x)


def nss_loadings(t: ArrayLike, tau1: float, tau2: float) -> FloatArray:
    """Factor loadings of the zero curve on (β₀, β₁, β₂, β₃).

    Equation:
        L(x) = (1 − e^(−x)) / x,   L(0) = 1
        X(t) = [1,  L(t/τ₁),  L(t/τ₁) − e^(−t/τ₁),  L(t/τ₂) − e^(−t/τ₂)]
    """
    times = as_float_array(t)
    l1, h1 = _level_and_hump(times, tau1)
    _, h2 = _level_and_hump(times, tau2)
    return np.column_stack((np.ones_like(times), l1, h1, h2))


@dataclass(frozen=True, slots=True)
class NelsonSiegelSvensson:
    beta0: float
    beta1: float
    beta2: float
    beta3: float
    tau1: float
    tau2: float

    def __post_init__(self) -> None:
        if self.tau1 <= 0 or self.tau2 <= 0:
            raise ValueError("τ₁ and τ₂ must be positive")

    @property
    def betas(self) -> FloatArray:
        return np.array([self.beta0, self.beta1, self.beta2, self.beta3])

    def zero_rate(self, t: ArrayLike) -> FloatArray:
        """Continuously compounded zero rate (GSW 2007, eq. 22).

        Equation:
            z(t) = β₀ + β₁·L(t/τ₁) + β₂·[L(t/τ₁) − e^(−t/τ₁)] + β₃·[L(t/τ₂) − e^(−t/τ₂)]
        """
        times = as_float_array(t)
        l1, h1 = _level_and_hump(times, self.tau1)
        _, h2 = _level_and_hump(times, self.tau2)
        return self.beta0 + self.beta1 * l1 + self.beta2 * h1 + self.beta3 * h2

    def forward_rate(self, t: ArrayLike) -> FloatArray:
        """Instantaneous forward rate (GSW 2007, eq. 21).

        Equation:
            f(t) = β₀ + β₁·e^(−t/τ₁) + β₂·(t/τ₁)·e^(−t/τ₁) + β₃·(t/τ₂)·e^(−t/τ₂)
        """
        times = as_float_array(t)
        x1, x2 = times / self.tau1, times / self.tau2
        e1, e2 = np.exp(-x1), np.exp(-x2)
        return self.beta0 + self.beta1 * e1 + self.beta2 * x1 * e1 + self.beta3 * x2 * e2

    def forward_slope(self, t: ArrayLike) -> FloatArray:
        """Maturity derivative of the instantaneous forward rate (needed by Hull–White θ(t)).

        Equation:
            ∂f/∂t = −(β₁/τ₁)·e^(−t/τ₁) + (β₂/τ₁)·(1 − t/τ₁)·e^(−t/τ₁) + (β₃/τ₂)·(1 − t/τ₂)·e^(−t/τ₂)
        """
        times = as_float_array(t)
        x1, x2 = times / self.tau1, times / self.tau2
        e1, e2 = np.exp(-x1), np.exp(-x2)
        return (
            -self.beta1 / self.tau1 * e1
            + self.beta2 / self.tau1 * (1 - x1) * e1
            + self.beta3 / self.tau2 * (1 - x2) * e2
        )

    def discount(self, t: ArrayLike) -> FloatArray:
        """Discount factor implied by the zero curve.

        Equation:
            DF(t) = e^(−z(t)·t)
        """
        times = as_float_array(t)
        return np.exp(-self.zero_rate(times) * times)


@dataclass(frozen=True, slots=True)
class NssFit:
    curve: NelsonSiegelSvensson
    rmse_bp: float
    max_abs_error_bp: float
    n_points: int


_TAU1_GRID = np.geomspace(0.1, 10.0, 25)
_TAU2_GRID = np.geomspace(0.5, 40.0, 25)
_MIN_TAU_GAP = 0.05


def _linear_betas(
    t: FloatArray, z: FloatArray, sqrt_w: FloatArray, tau1: float, tau2: float
) -> tuple[FloatArray, float]:
    """β for fixed τ's under β₀ ≥ 0, β₀ + β₁ ≥ 0, solved in (β₀, γ = β₀ + β₁, β₂, β₃)."""
    x = nss_loadings(t, tau1, tau2)
    design = np.column_stack((1 - x[:, 1], x[:, 1], x[:, 2], x[:, 3])) * sqrt_w[:, None]
    lower = np.array([0.0, 0.0, -np.inf, -np.inf])
    upper = np.full(4, np.inf)
    sol = lsq_linear(design, z * sqrt_w, bounds=(lower, upper), method="bvls")
    b0, gamma, b2, b3 = (float(v) for v in sol.x)
    return np.array([b0, gamma - b0, b2, b3]), float(2 * sol.cost)


def _level_hump_tau_derivatives(t: FloatArray, tau: float) -> tuple[FloatArray, FloatArray]:
    """∂L(t/τ)/∂τ and ∂H(t/τ)/∂τ, with H = L − e^(−x); stable as x = t/τ → 0."""
    x = t / tau
    safe = np.where(x > 1e-8, x, 1.0)
    # dL/dx = (e^(−x)(1 + x) − 1)/x², written with expm1 to avoid cancellation at small x.
    dl_dx = np.where(x > 1e-8, ((1 + safe) * np.expm1(-safe) + safe) / safe**2, -0.5)
    dx_dtau = -x / tau
    dl = dl_dx * dx_dtau
    return dl, (dl_dx + np.exp(-x)) * dx_dtau


def fit_nss(
    maturities: ArrayLike,
    zero_rates: ArrayLike,
    *,
    weights: ArrayLike | None = None,
) -> NssFit:
    """Fit NSS to continuously compounded zero rates (decimals) at the given maturities (years).

    The objective has several basins in (τ₁, τ₂) — a short-end hump below the first maturity is
    weakly identified — so stage 2 polishes one seed per τ₁ grid row (the best τ₂ for it) rather
    than the overall best few, which can all sit in one wrong basin.

    Equation:
        min_θ Σᵢ wᵢ·(z(tᵢ; θ) − zᵢ)²   s.t.  β₀ ≥ 0,  β₀ + β₁ ≥ 0,  0 < τ₁ < τ₂
        stage 1: for each grid (τ₁, τ₂), bounded linear LS in (β₀, γ = β₀ + β₁, β₂, β₃)
        stage 2: trust-region-reflective LS on (β₀, γ, β₂, β₃, τ₁, δ = τ₂ − τ₁) with the analytic
                 Jacobian: every per-τ₁ seed for ≤100 evaluations, the best three to convergence
    """
    t, z = as_float_array(maturities), as_float_array(zero_rates)
    if t.ndim != 1 or t.shape != z.shape or t.size < 6:
        raise ValueError("need at least six (maturity, zero rate) points")
    if np.any(t <= 0):
        raise ValueError("maturities must be positive")
    w = np.ones_like(t) if weights is None else as_float_array(weights)
    if w.shape != t.shape or np.any(w < 0):
        raise ValueError("weights must be non-negative, one per point")
    sqrt_w = np.sqrt(w)

    seeds: list[tuple[FloatArray, float, float]] = []
    for tau1 in (float(v) for v in _TAU1_GRID):
        row = [
            (*_linear_betas(t, z, sqrt_w, tau1, float(tau2)), float(tau2))
            for tau2 in _TAU2_GRID[tau1 + _MIN_TAU_GAP < _TAU2_GRID]
        ]
        betas, _, tau2 = min(row, key=lambda candidate: candidate[1])
        seeds.append((betas, tau1, tau2))

    def residuals_bp(p: FloatArray) -> FloatArray:
        b0, gamma, b2, b3, tau1, gap = p
        curve = NelsonSiegelSvensson(b0, gamma - b0, b2, b3, tau1, tau1 + gap)
        return (curve.zero_rate(t) - z) * sqrt_w * 1e4

    def jacobian_bp(p: FloatArray) -> FloatArray:
        """∂residual/∂(β₀, γ, β₂, β₃, τ₁, δ) in closed form (τ₂ = τ₁ + δ)."""
        b0, gamma, b2, b3, tau1, gap = p
        l1, h1 = _level_and_hump(t, tau1)
        _, h2 = _level_and_hump(t, tau1 + gap)
        dl1, dh1 = _level_hump_tau_derivatives(t, tau1)
        _, dh2 = _level_hump_tau_derivatives(t, tau1 + gap)
        d_tau1 = (gamma - b0) * dl1 + b2 * dh1 + b3 * dh2
        columns = (1 - l1, l1, h1, h2, d_tau1, b3 * dh2)
        return np.column_stack(columns) * (sqrt_w * 1e4)[:, None]

    lower = np.array([0.0, 0.0, -np.inf, -np.inf, 0.02, _MIN_TAU_GAP])
    upper = np.array([np.inf, np.inf, np.inf, np.inf, 30.0, 60.0])

    def polish(x0: FloatArray, max_nfev: int) -> tuple[float, FloatArray]:
        sol = least_squares(
            residuals_bp,
            np.clip(x0, lower, upper),
            jac=jacobian_bp,
            bounds=(lower, upper),
            method="trf",
            x_scale="jac",
            max_nfev=max_nfev,
        )
        return float(np.sum(sol.fun**2)), np.asarray(sol.x, dtype=np.float64)

    # Explore every basin cheaply, then converge fully from the three most promising.
    explored = sorted(
        (
            polish(np.array([b[0], b[0] + b[1], b[2], b[3], tau1, tau2 - tau1]), 100)
            for b, tau1, tau2 in seeds
        ),
        key=lambda candidate: candidate[0],
    )
    best = min((polish(x, 2_000) for _, x in explored[:3]), key=lambda candidate: candidate[0])
    b0, gamma, b2, b3, tau1, gap = (float(v) for v in best[1])
    curve = NelsonSiegelSvensson(b0, gamma - b0, b2, b3, tau1, tau1 + gap)
    errors_bp = (curve.zero_rate(t) - z) * 1e4
    return NssFit(
        curve=curve,
        rmse_bp=float(np.sqrt(np.mean(errors_bp**2))),
        max_abs_error_bp=float(np.max(np.abs(errors_bp))),
        n_points=int(t.size),
    )
