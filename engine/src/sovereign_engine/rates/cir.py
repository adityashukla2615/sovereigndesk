"""Cox–Ingersoll–Ross (1985) short-rate model: dr = a·(b − r)·dt + σ·√r·dW."""

import math
from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


@dataclass(frozen=True, slots=True)
class CIR:
    a: float
    """Mean-reversion speed (per year)."""
    b: float
    """Long-run mean of r."""
    sigma: float
    """Volatility scale: the instantaneous volatility is σ·√r."""

    def __post_init__(self) -> None:
        if self.a <= 0 or self.b <= 0 or self.sigma <= 0:
            raise ValueError("need a > 0, b > 0 and σ > 0")

    def feller(self) -> bool:
        """True when the Feller condition holds, so r never reaches zero.

        Equation:
            2·a·b ≥ σ²
        """
        return 2 * self.a * self.b >= self.sigma**2

    def mean(self, r0: ArrayLike, t: float) -> FloatArray:
        """Conditional mean of r_t given r_0.

        Equation:
            E[r_t] = r₀·e^(−a·t) + b·(1 − e^(−a·t))
        """
        decay = math.exp(-self.a * t)
        return as_float_array(r0) * decay + self.b * (1 - decay)

    def variance(self, r0: ArrayLike, t: float) -> FloatArray:
        """Conditional variance of r_t given r_0.

        Equation:
            Var[r_t] = r₀·(σ²/a)·(e^(−a·t) − e^(−2a·t)) + b·σ²/(2a)·(1 − e^(−a·t))²
        """
        e1, e2 = math.exp(-self.a * t), math.exp(-2 * self.a * t)
        s2 = self.sigma**2
        return (
            as_float_array(r0) * s2 / self.a * (e1 - e2)
            + self.b * s2 / (2 * self.a) * (1 - e1) ** 2
        )

    def step(self, r: ArrayLike, dt: float, rng: np.random.Generator) -> FloatArray:
        """Exact transition: a scaled noncentral chi-square draw (Glasserman 2003, §3.4).

        Equation:
            r_{t+Δ} = c · χ'²_d(λ),   c = σ²·(1 − e^(−aΔ))/(4a),   d = 4ab/σ²,   λ = r_t·e^(−aΔ)/c
        """
        rates = np.maximum(as_float_array(r), 0.0)
        c = self.sigma**2 * -math.expm1(-self.a * dt) / (4 * self.a)
        d = 4 * self.a * self.b / self.sigma**2
        nonc = rates * math.exp(-self.a * dt) / c
        return c * rng.noncentral_chisquare(d, nonc, size=rates.shape)

    def bond_price(self, r: ArrayLike, tau: ArrayLike) -> FloatArray:
        """Zero-coupon bond price for time to maturity ``tau``.

        Evaluated with e^(−hτ) (numerator and denominator divided by e^(hτ)) so that long
        maturities cannot overflow.

        Equation:
            h = √(a² + 2σ²),   D(τ) = (h + a)·(e^(hτ) − 1) + 2h
            B(τ) = 2·(e^(hτ) − 1) / D(τ)
            A(τ) = [2h·e^((a + h)τ/2) / D(τ)]^(2ab/σ²)
            P(τ) = A(τ)·e^(−B(τ)·r)
        """
        rates, taus = as_float_array(r), as_float_array(tau)
        h = math.sqrt(self.a**2 + 2 * self.sigma**2)
        decay = np.exp(-h * taus)
        one_minus = -np.expm1(-h * taus)
        scaled = (h + self.a) * one_minus + 2 * h * decay  # D(τ)·e^(−hτ)
        b_tau = 2 * one_minus / scaled
        log_a = (2 * self.a * self.b / self.sigma**2) * (
            math.log(2 * h) + (self.a - h) * taus / 2 - np.log(scaled)
        )
        return np.exp(log_a - b_tau * rates)

    def zero_rate(self, r: ArrayLike, tau: ArrayLike) -> FloatArray:
        """Continuously compounded zero rate implied by the model.

        Equation:
            R(τ) = −ln P(τ) / τ
        """
        taus = as_float_array(tau)
        return -np.log(self.bond_price(r, taus)) / taus
