"""Nelson–Siegel–Svensson curve, in the parameterisation of Gürkaynak, Sack and Wright (2007).

The Fed's daily GSW dataset (feds200628) publishes β₀…β₃, τ₁, τ₂ in this form; zero yields are
continuously compounded. Here rates are decimals, so the published percent β's divide by 100.

Fitting is two-stage: for fixed (τ₁, τ₂) the zero curve is linear in β, so a grid of (τ₁, τ₂)
pairs is scanned with bound-constrained linear least squares, then the best few seeds are
polished by bounded nonlinear least squares over all six parameters. ``fit_nss_quotes`` fits
market quotes instead of zero rates (bills at their simple yield, bonds at their par yield),
and can start from the previous fit so a live curve refits cheaply on every tick.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

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


def _zero_jacobian(t: FloatArray, p: FloatArray) -> FloatArray:
    """∂z(t)/∂(β₀, γ, β₂, β₃, τ₁, δ) in closed form (γ = β₀ + β₁, τ₂ = τ₁ + δ)."""
    b0, gamma, b2, b3, tau1, gap = p
    l1, h1 = _level_and_hump(t, tau1)
    _, h2 = _level_and_hump(t, tau1 + gap)
    dl1, dh1 = _level_hump_tau_derivatives(t, tau1)
    _, dh2 = _level_hump_tau_derivatives(t, tau1 + gap)
    d_tau1 = (gamma - b0) * dl1 + b2 * dh1 + b3 * dh2
    return np.column_stack((1 - l1, l1, h1, h2, d_tau1, b3 * dh2))


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
        return _zero_jacobian(t, p) * (sqrt_w * 1e4)[:, None]

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


QuoteKind = Literal["bill", "par"]


@dataclass(frozen=True, slots=True)
class Quote:
    """A quoted yield the fitted curve should reproduce."""

    years: float
    rate: float
    """Decimal yield: simple (money-market) for a bill, the coupon of a par bond."""
    kind: QuoteKind


@dataclass(frozen=True, slots=True)
class _QuoteGrid:
    """Where each quote reads the curve: bill maturities, and the coupon grid for par bonds."""

    bills: FloatArray
    bill_rows: FloatArray
    grid: FloatArray
    par_periods: FloatArray
    par_rows: FloatArray
    freq: int

    @classmethod
    def build(cls, quotes: Sequence[Quote], freq: int) -> "_QuoteGrid":
        if freq < 1:
            raise ValueError("need at least one coupon a year")
        bill_rows = [i for i, q in enumerate(quotes) if q.kind == "bill"]
        par_rows = [i for i, q in enumerate(quotes) if q.kind == "par"]
        periods = [round(quotes[i].years * freq) for i in par_rows]
        for i, n in zip(par_rows, periods, strict=True):
            if n < 1 or not math.isclose(n / freq, quotes[i].years, abs_tol=1e-9):
                raise ValueError("a par bond's maturity must be a whole number of coupon periods")
        if any(quotes[i].years <= 0 for i in bill_rows):
            raise ValueError("bill maturities must be positive")
        return cls(
            bills=np.array([quotes[i].years for i in bill_rows], dtype=np.float64),
            bill_rows=np.array(bill_rows, dtype=np.int64),
            grid=np.arange(1, max(periods, default=0) + 1, dtype=np.float64) / freq,
            par_periods=np.array(periods, dtype=np.int64),
            par_rows=np.array(par_rows, dtype=np.int64),
            freq=freq,
        )

    def yields(self, curve: NelsonSiegelSvensson, size: int) -> FloatArray:
        out = np.empty(size, dtype=np.float64)
        if self.bills.size:
            out[self.bill_rows] = (1 / curve.discount(self.bills) - 1) / self.bills
        if self.par_rows.size:
            dfs = curve.discount(self.grid)
            annuity = np.cumsum(dfs)
            n = self.par_periods - 1
            out[self.par_rows] = self.freq * (1 - dfs[n]) / annuity[n]
        return out

    def jacobian(self, curve: NelsonSiegelSvensson, p: FloatArray, size: int) -> FloatArray:
        """∂yield/∂(β₀, γ, β₂, β₃, τ₁, δ): bills ∂y = e^(zT)·∂z; par bonds by the quotient rule
        on y = f·(1 − Dₙ)/Aₙ with ∂Dₖ = −tₖ·Dₖ·∂zₖ and ∂Aₙ = Σ_{k≤n} ∂Dₖ."""
        out = np.empty((size, 6), dtype=np.float64)
        if self.bills.size:
            growth = 1 / curve.discount(self.bills)
            out[self.bill_rows] = _zero_jacobian(self.bills, p) * growth[:, None]
        if self.par_rows.size:
            dfs = curve.discount(self.grid)
            d_dfs = -(self.grid * dfs)[:, None] * _zero_jacobian(self.grid, p)
            annuity, d_annuity = np.cumsum(dfs), np.cumsum(d_dfs, axis=0)
            n = self.par_periods - 1
            a, d_a = annuity[n][:, None], d_annuity[n]
            out[self.par_rows] = self.freq * (-d_dfs[n] * a - (1 - dfs[n])[:, None] * d_a) / a**2
        return out


def quote_yields(curve: NelsonSiegelSvensson, quotes: Sequence[Quote], freq: int = 2) -> FloatArray:
    """The yield the curve implies for each quoted instrument.

    Equation:
        bill (zero coupon, simple yield):   y = (1/DF(T) − 1) / T
        par bond paying f coupons a year:    y = f·(1 − DF(T)) / Σ_{k=1}^{fT} DF(k/f)
    """
    return _QuoteGrid.build(quotes, freq).yields(curve, len(quotes))


def _approximate_zeros(quotes: Sequence[Quote], freq: int) -> FloatArray:
    return np.array(
        [
            math.log1p(q.rate * q.years) / q.years
            if q.kind == "bill"
            else freq * math.log1p(q.rate / freq)
            for q in quotes
        ]
    )


def fit_nss_quotes(
    quotes: Sequence[Quote],
    *,
    freq: int = 2,
    start: NssFit | None = None,
    warm_tolerance_bp: float = 1.0,
) -> NssFit:
    """Fit NSS to quoted bill and par-bond yields, starting from a previous fit when given.

    Cold, zero rates approximated from the quotes seed ``fit_nss``; either way all six
    parameters are then polished on the yield errors. A warm start whose RMSE ends more than
    ``warm_tolerance_bp`` above the previous fit's falls back to the cold fit.

    Equation:
        min_θ Σᵢ (yᵢ(θ) − ŷᵢ)²,  yᵢ from ``quote_yields``,  s.t.  β₀ ≥ 0,  β₀ + β₁ ≥ 0,  0 < τ₁ < τ₂
        cold seed: bills zᵢ = ln(1 + ŷᵢ·Tᵢ)/Tᵢ,  par bonds zᵢ ≈ f·ln(1 + ŷᵢ/f)
    """
    if len(quotes) < 6:
        raise ValueError("need at least six quotes")
    layout = _QuoteGrid.build(quotes, freq)
    target = np.array([q.rate for q in quotes], dtype=np.float64)

    def curve_of(p: FloatArray) -> NelsonSiegelSvensson:
        b0, gamma, b2, b3, tau1, gap = (float(v) for v in p)
        return NelsonSiegelSvensson(b0, gamma - b0, b2, b3, tau1, tau1 + gap)

    def residuals_bp(p: FloatArray) -> FloatArray:
        return (layout.yields(curve_of(p), target.size) - target) * 1e4

    def jacobian_bp(p: FloatArray) -> FloatArray:
        return layout.jacobian(curve_of(p), p, target.size) * 1e4

    lower = np.array([0.0, 0.0, -np.inf, -np.inf, 0.02, _MIN_TAU_GAP])
    upper = np.array([np.inf, np.inf, np.inf, np.inf, 30.0, 60.0])

    def polish(seed: NelsonSiegelSvensson, max_nfev: int) -> NssFit:
        x0 = np.array(
            [seed.beta0, seed.beta0 + seed.beta1, seed.beta2, seed.beta3, seed.tau1,
             seed.tau2 - seed.tau1]
        )  # fmt: skip
        sol = least_squares(
            residuals_bp,
            np.clip(x0, lower, upper),
            jac=jacobian_bp,
            bounds=(lower, upper),
            method="trf",
            x_scale="jac",
            max_nfev=max_nfev,
        )
        curve = curve_of(np.asarray(sol.x, dtype=np.float64))
        errors = np.asarray(sol.fun, dtype=np.float64)
        return NssFit(
            curve=curve,
            rmse_bp=float(np.sqrt(np.mean(errors**2))),
            max_abs_error_bp=float(np.max(np.abs(errors))),
            n_points=len(quotes),
        )

    warm: NssFit | None = None
    if start is not None:
        warm = polish(start.curve, 60)
        if warm.rmse_bp <= start.rmse_bp + warm_tolerance_bp:
            return warm
    times = np.array([q.years for q in quotes], dtype=np.float64)
    cold = polish(fit_nss(times, _approximate_zeros(quotes, freq)).curve, 2_000)
    return cold if warm is None or cold.rmse_bp < warm.rmse_bp else warm
