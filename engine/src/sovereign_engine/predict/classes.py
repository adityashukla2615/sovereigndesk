"""The five decision classes the predictor chooses between.

RBI moves the repo rate in steps of 25 basis points as a rule; larger moves (35, 40, 50, 75 bp)
have come in tightening cycles and crises. A "big" move is anything beyond one step.
"""

import numpy as np

from sovereign_engine._types import ArrayLike, IntArray, as_float_array

CLASSES: tuple[str, ...] = ("big cut", "cut", "hold", "hike", "big hike")
HOLD = 2
STEP = 0.0025
"""One policy step, 25 basis points (decimal)."""


def decision_class(change: ArrayLike, *, step: float = STEP, tol: float = 1e-6) -> IntArray:
    """The class index (0 = big cut … 4 = big hike) of each repo change (decimals).

    Equation:
        class(Δ) = 0 if Δ < −s − ε;  1 if −s − ε ≤ Δ < −ε;  2 if |Δ| ≤ ε;
                   3 if ε < Δ ≤ s + ε;  4 if Δ > s + ε        (s = 25 bp, ε = 1e-6)
    """
    d = as_float_array(change)
    out = np.full(d.shape, HOLD, dtype=np.int64)
    out[d < -tol] = 1
    out[d < -step - tol] = 0
    out[d > tol] = 3
    out[d > step + tol] = 4
    return out
