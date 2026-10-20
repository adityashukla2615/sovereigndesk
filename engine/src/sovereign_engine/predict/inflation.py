"""Core inflation from published CPI indices when the weights are not published with them.

A fixed-base (Laspeyres) price index is the weighted mean of its components' indices with the
base period's expenditure weights, so the weights can be recovered from the published indices
themselves by least squares (non-negative, summing to one). Removing components from the total
with those weights gives an exclusion ("core") index.
"""

import numpy as np
from scipy.optimize import lsq_linear

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


def component_weights(total: ArrayLike, components: ArrayLike) -> tuple[FloatArray, float]:
    """Weights w ≥ 0, Σw = 1, that best rebuild the total index from its components, and the
    RMS rebuild error (index points).

    Equation:
        min_w ‖C·w − I‖²  s.t.  wₖ ≥ 0,  Σₖ wₖ = 1      (C: periods × components)
        solved as bounded least squares with the constraint as a heavily weighted extra row
    """
    t, c = as_float_array(total), np.atleast_2d(as_float_array(components))
    if c.shape[0] != t.size or t.size < c.shape[1]:
        raise ValueError("need at least as many periods as components, one row per period")
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(c))):
        raise ValueError("indices must be finite")
    penalty = 1e4 * float(np.mean(np.abs(t)))
    design = np.vstack((c, np.full((1, c.shape[1]), penalty)))
    target = np.concatenate((t, [penalty]))
    sol = lsq_linear(design, target, bounds=(0.0, 1.0), method="bvls")
    weights = np.asarray(sol.x, dtype=np.float64)
    weights = weights / weights.sum()
    rmse = float(np.sqrt(np.mean((c @ weights - t) ** 2)))
    return weights, rmse


def exclusion_index(total: ArrayLike, excluded: ArrayLike, weights: ArrayLike) -> FloatArray:
    """The total index without some components (each column of ``excluded``, with its weight).

    Equation:
        I_core = (I − Σⱼ wⱼ·Iⱼ) / (1 − Σⱼ wⱼ)
    """
    t = as_float_array(total)
    x = np.atleast_2d(as_float_array(excluded))
    w = as_float_array(weights)
    if x.ndim == 2 and x.shape[0] != t.size:
        x = x.T
    if x.shape != (t.size, w.size) or not 0 < w.sum() < 1:
        raise ValueError("need one column per excluded weight, and weights summing below one")
    return np.asarray((t - x @ w) / (1 - w.sum()), dtype=np.float64)
