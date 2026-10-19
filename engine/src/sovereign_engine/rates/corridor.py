"""A mean-reverting rate that can never leave its policy corridor (logit-OU).

The rate r ∈ (L, U) is mapped to an unbounded state x by the logit; x follows an OU process
that reverts to the logit of the target, so r reverts to the target and stays strictly inside
the corridor by construction. Used for WACR inside [SDF, MSF] and EFFR inside the Fed's range.
"""

import math

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array

_EDGE = 1e-12
_X_CLIP = 30.0


def _check_corridor(lower: float, upper: float) -> None:
    if not upper > lower:
        raise ValueError("the corridor needs upper > lower")


def to_logit(r: ArrayLike, lower: float, upper: float) -> FloatArray:
    """Map a rate inside (L, U) to the real line (rates on or past a bound are clipped inside).

    Equation:
        u = (r − L)/(U − L),   x = ln(u / (1 − u))
    """
    _check_corridor(lower, upper)
    u = np.clip((as_float_array(r) - lower) / (upper - lower), _EDGE, 1 - _EDGE)
    return np.log(u / (1 - u))


def from_logit(x: ArrayLike, lower: float, upper: float) -> FloatArray:
    """Map a state on the real line back into the open corridor (L, U).

    Equation:
        r = L + (U − L) / (1 + e^(−x))
    """
    _check_corridor(lower, upper)
    state = np.clip(as_float_array(x), -_X_CLIP, _X_CLIP)
    return lower + (upper - lower) / (1 + np.exp(-state))


def logit_sigma_for(sigma_r: float, lower: float, upper: float, target: float) -> float:
    """Logit-space volatility giving rate volatility ``sigma_r`` near the target (delta method).

    Equation:
        p = (target − L)/(U − L),   dr/dx = (U − L)·p·(1 − p)   ⇒   σ_x = σ_r / ((U − L)·p·(1 − p))
    """
    _check_corridor(lower, upper)
    p = (target - lower) / (upper - lower)
    if not 0 < p < 1:
        raise ValueError("target must lie strictly inside the corridor")
    return sigma_r / ((upper - lower) * p * (1 - p))


def corridor_ou_step(
    r: ArrayLike,
    *,
    lower: float,
    upper: float,
    target: float,
    kappa: float,
    sigma_x: float,
    dt: float,
    rng: np.random.Generator,
) -> FloatArray:
    """One exact OU step in logit space; bounds and target may change between steps.

    Equation:
        μ = logit(target),   x = logit(r)
        x' = μ + (x − μ)·e^(−κΔ) + σ_x·√((1 − e^(−2κΔ))/(2κ)) · Z,   Z ~ N(0, 1)
        r' = L + (U − L)/(1 + e^(−x'))  ∈ (L, U)
    """
    if kappa <= 0 or sigma_x < 0:
        raise ValueError("need κ > 0 and σ_x ≥ 0")
    if not lower < target < upper:
        raise ValueError("target must lie strictly inside the corridor")
    x = to_logit(r, lower, upper)
    mu = float(to_logit(target, lower, upper))
    decay = math.exp(-kappa * dt)
    sd = sigma_x * math.sqrt(-math.expm1(-2 * kappa * dt) / (2 * kappa))
    return from_logit(mu + (x - mu) * decay + sd * rng.standard_normal(x.shape), lower, upper)
