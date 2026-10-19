"""Vasicek (1977) short-rate model: dr = a·(b − r)·dt + σ·dW."""

import math
from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


@dataclass(frozen=True, slots=True)
class Vasicek:
    a: float
    """Mean-reversion speed (per year)."""
    b: float
    """Long-run mean of r."""
    sigma: float
    """Absolute volatility of r (per √year)."""

    def __post_init__(self) -> None:
        if self.a <= 0 or self.sigma < 0:
            raise ValueError("need a > 0 and σ ≥ 0")

    def mean(self, r0: ArrayLike, t: float) -> FloatArray:
        """Conditional mean of r_t given r_0.

        Equation:
            E[r_t] = r₀·e^(−a·t) + b·(1 − e^(−a·t))
        """
        decay = math.exp(-self.a * t)
        return as_float_array(r0) * decay + self.b * (1 - decay)

    def variance(self, t: float) -> float:
        """Conditional variance of r_t (independent of r_0).

        Equation:
            Var[r_t] = σ²/(2a) · (1 − e^(−2a·t))
        """
        return self.sigma**2 / (2 * self.a) * -math.expm1(-2 * self.a * t)

    def step(self, r: ArrayLike, dt: float, rng: np.random.Generator) -> FloatArray:
        """Exact transition over ``dt`` (the OU transition density is Gaussian).

        Equation:
            r_{t+Δ} = r_t·e^(−aΔ) + b·(1 − e^(−aΔ)) + σ·√((1 − e^(−2aΔ))/(2a)) · Z,   Z ~ N(0, 1)
        """
        rates = as_float_array(r)
        z = rng.standard_normal(rates.shape)
        return self.mean(rates, dt) + math.sqrt(self.variance(dt)) * z

    def bond_price(self, r: ArrayLike, tau: ArrayLike) -> FloatArray:
        """Zero-coupon bond price for time to maturity ``tau``.

        Equation:
            P(τ) = A(τ)·e^(−B(τ)·r)
            B(τ) = (1 − e^(−aτ)) / a
            ln A(τ) = (b − σ²/(2a²))·(B(τ) − τ) − σ²·B(τ)²/(4a)
        """
        rates, taus = as_float_array(r), as_float_array(tau)
        b_tau = -np.expm1(-self.a * taus) / self.a
        log_a = (self.b - self.sigma**2 / (2 * self.a**2)) * (b_tau - taus) - (
            self.sigma**2 * b_tau**2 / (4 * self.a)
        )
        return np.exp(log_a - b_tau * rates)

    def zero_rate(self, r: ArrayLike, tau: ArrayLike) -> FloatArray:
        """Continuously compounded zero rate implied by the model.

        Equation:
            R(τ) = −ln P(τ) / τ
        """
        taus = as_float_array(tau)
        return -np.log(self.bond_price(r, taus)) / taus
