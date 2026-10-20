"""How often RBI runs a fine-tuning auction at a given liquidity position.

RBI does not follow a published trigger: on days of similar liquidity it sometimes holds a VRR
or VRRR and sometimes not. A logistic regression of "a new operation was held" on the previous
day's surplus (per cent of NDTL) captures that as a probability, fitted to RBI's history.
"""

import math
from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


@dataclass(frozen=True, slots=True)
class ReactionCurve:
    intercept: float
    slope: float
    """Per percentage point of NDTL."""

    def probability(self, surplus_pct: ArrayLike) -> FloatArray:
        """Chance of an operation at a previous-day surplus of ``surplus_pct`` % of NDTL.

        Equation:
            p(ℓ) = 1 / (1 + e^(−(a + b·ℓ)))
        """
        z = np.clip(self.intercept + self.slope * as_float_array(surplus_pct), -60, 60)
        return 1 / (1 + np.exp(-z))


def fit_reaction(
    surplus_pct: ArrayLike, happened: ArrayLike, iterations: int = 50
) -> ReactionCurve:
    """Maximum-likelihood logistic regression by iteratively reweighted least squares.

    Equation:
        max Σᵢ yᵢ·ln pᵢ + (1 − yᵢ)·ln(1 − pᵢ),  pᵢ = p(ℓᵢ)
        Newton step: θ ← θ + (XᵀWX)⁻¹Xᵀ(y − p),  W = diag(pᵢ(1 − pᵢ)),  X = [1, ℓ]
    """
    x, y = as_float_array(surplus_pct), as_float_array(happened)
    if x.shape != y.shape or x.ndim != 1 or x.size < 8:
        raise ValueError("need at least eight observations")
    if not 0 < y.sum() < y.size:
        raise ValueError("need both days with and without an operation")
    design = np.column_stack([np.ones_like(x), x])
    rate = float(y.mean())
    theta = np.array([math.log(rate / (1 - rate)), 0.0])
    for _ in range(iterations):
        p = 1 / (1 + np.exp(-np.clip(design @ theta, -60, 60)))
        w = p * (1 - p)
        hessian = design.T @ (design * w[:, None]) + 1e-9 * np.eye(2)
        step = np.linalg.solve(hessian, design.T @ (y - p))
        theta = theta + step
        if float(np.max(np.abs(step))) < 1e-10:
            break
    return ReactionCurve(float(theta[0]), float(theta[1]))
