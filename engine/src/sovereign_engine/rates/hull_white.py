"""Hull–White one-factor model fitted to today's curve: dr = (θ(t) − a·r)·dt + σ·dW.

Simulation uses the decomposition r(t) = x(t) + α(t) of Brigo and Mercurio (2006, §3.3), where
x is a zero-mean OU process and α absorbs the fit to the initial curve. This needs only the
initial forward curve, not its derivative, so θ(t) is reported for completeness and teaching.
"""

import math
from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array
from sovereign_engine.curves.base import Curve


@dataclass(frozen=True, slots=True)
class HullWhite:
    a: float
    """Mean-reversion speed (per year)."""
    sigma: float
    """Absolute volatility of r (per √year)."""
    curve: Curve
    """Initial term structure P^M(0, T) that the model reprices exactly."""

    def __post_init__(self) -> None:
        if self.a <= 0 or self.sigma < 0:
            raise ValueError("need a > 0 and σ ≥ 0")

    def loading(self, t: ArrayLike, maturity: ArrayLike) -> FloatArray:
        """Sensitivity of ln P(t, T) to the short rate.

        Equation:
            B(t, T) = (1 − e^(−a·(T − t))) / a
        """
        tau = as_float_array(maturity) - as_float_array(t)
        return -np.expm1(-self.a * tau) / self.a

    def alpha(self, t: ArrayLike) -> FloatArray:
        """Deterministic shift that makes the model fit the initial curve.

        Equation:
            α(t) = f^M(0, t) + σ²/(2a²) · (1 − e^(−a·t))²
        """
        times = as_float_array(t)
        return self.curve.forward_rate(times) + self.sigma**2 / (2 * self.a**2) * (
            np.expm1(-self.a * times) ** 2
        )

    def theta(self, t: ArrayLike, *, h: float = 1e-5) -> FloatArray:
        """Drift function θ(t) fitted to the initial curve.

        Uses the curve's analytic ``forward_slope`` when it has one (e.g. NSS), otherwise a
        central difference of the forward curve.

        Equation:
            θ(t) = ∂f^M(0, t)/∂t + a·f^M(0, t) + σ²/(2a) · (1 − e^(−2a·t))
        """
        times = as_float_array(t)
        slope_fn = getattr(self.curve, "forward_slope", None)
        if callable(slope_fn):
            slope = as_float_array(slope_fn(times))
        else:
            lo = np.maximum(times - h, 0.0)
            slope = (self.curve.forward_rate(times + h) - self.curve.forward_rate(lo)) / (
                times + h - lo
            )
        return (
            slope
            + self.a * self.curve.forward_rate(times)
            - self.sigma**2 / (2 * self.a) * (np.expm1(-2 * self.a * times))
        )

    def step_x(self, x: ArrayLike, dt: float, rng: np.random.Generator) -> FloatArray:
        """Exact transition of the zero-mean OU factor.

        Equation:
            x_{t+Δ} = x_t·e^(−aΔ) + σ·√((1 − e^(−2aΔ))/(2a)) · Z,   Z ~ N(0, 1),   x₀ = 0
        """
        state = as_float_array(x)
        sd = self.sigma * math.sqrt(-math.expm1(-2 * self.a * dt) / (2 * self.a))
        return state * math.exp(-self.a * dt) + sd * rng.standard_normal(state.shape)

    def short_rate(self, x: ArrayLike, t: float) -> FloatArray:
        """Short rate from the OU factor.

        Equation:
            r(t) = x(t) + α(t)
        """
        return as_float_array(x) + float(self.alpha(t))

    def bond_price(self, t: float, maturity: ArrayLike, r: ArrayLike) -> FloatArray:
        """Zero-coupon bond price P(t, T) given the short rate at t (Brigo–Mercurio eq. 3.39).

        Equation:
            P(t, T) = A(t, T)·e^(−B(t, T)·r(t))
            ln A(t, T) = ln(P^M(0, T)/P^M(0, t)) + B(t, T)·f^M(0, t)
                         − σ²/(4a)·(1 − e^(−2a·t))·B(t, T)²
        """
        maturities = as_float_array(maturity)
        b_tt = self.loading(t, maturities)
        df_t = float(self.curve.discount(t))
        f_t = float(self.curve.forward_rate(t))
        log_a = (
            np.log(self.curve.discount(maturities) / df_t)
            + b_tt * f_t
            - self.sigma**2 / (4 * self.a) * -math.expm1(-2 * self.a * t) * b_tt**2
        )
        # Result shape is r.shape + T.shape: one curve per simulated short rate.
        return np.exp(log_a - np.multiply.outer(as_float_array(r), b_tt))

    def zero_rates(self, t: float, tenors: ArrayLike, r: ArrayLike) -> FloatArray:
        """The model's whole zero curve at time t, for tenors τ = T − t.

        Equation:
            R(t, t + τ) = −ln P(t, t + τ) / τ
        """
        taus = as_float_array(tenors)
        return -np.log(self.bond_price(t, t + taus, r)) / taus
