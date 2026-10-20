"""Walk-forward backtests: each decision is forecast by models fitted only on earlier ones.

The window expands: the forecast for decision k uses decisions 0 … k−1, with the features as
they stood before decision k (the dataset's job). Two naive forecasts set the bar: repeating
the last decision, and always holding.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, IntArray, as_float_array
from sovereign_engine.predict.classes import HOLD
from sovereign_engine.predict.metrics import accuracy, brier_score, confusion_matrix, macro_f1


class Predictor(Protocol):
    def predict_proba(self, features: ArrayLike) -> FloatArray: ...


type Fitter = Callable[[FloatArray, IntArray], Predictor]


@dataclass(frozen=True, slots=True)
class ModelReport:
    probabilities: FloatArray
    """One row of five class probabilities per forecast decision."""
    predicted: IntArray
    """The most probable class (the lower one on a tie)."""
    accuracy: float
    macro_f1: float
    brier: float
    confusion: IntArray


@dataclass(frozen=True, slots=True)
class Backtest:
    rows: IntArray
    """Indices of the forecast decisions."""
    actual: IntArray
    reports: dict[str, ModelReport]


def _report(actual: IntArray, probabilities: FloatArray) -> ModelReport:
    predicted = np.argmax(probabilities, axis=1).astype(np.int64)
    return ModelReport(
        probabilities=probabilities,
        predicted=predicted,
        accuracy=accuracy(actual, predicted),
        macro_f1=macro_f1(actual, predicted),
        brier=brier_score(actual, probabilities),
        confusion=confusion_matrix(actual, predicted),
    )


def _onehot(classes: IntArray) -> FloatArray:
    out = np.zeros((classes.size, 5))
    out[np.arange(classes.size), classes] = 1.0
    return out


def walk_forward(
    features: ArrayLike, classes: ArrayLike, fitters: Mapping[str, Fitter], *, start: int
) -> Backtest:
    """Expanding-window forecasts of every decision from ``start`` on, plus the two baselines.

    Equation:
        p̂ₖ = model fitted on {(xⱼ, yⱼ) : j < k}, applied to xₖ,   k = start … n − 1
        repeat last: ŷₖ = yₖ₋₁;   always hold: ŷₖ = hold
    """
    x = np.atleast_2d(as_float_array(features))
    y = np.asarray(classes, dtype=np.int64)
    if x.shape[0] != y.size or not 1 <= start < y.size:
        raise ValueError("need one class per row and 1 ≤ start < number of decisions")
    rows = np.arange(start, y.size)
    actual = y[rows]
    probabilities: dict[str, list[FloatArray]] = {name: [] for name in fitters}
    for k in rows:
        for name, fit in fitters.items():
            probabilities[name].append(fit(x[:k], y[:k]).predict_proba(x[k : k + 1])[0])
    reports = {name: _report(actual, np.array(rows_)) for name, rows_ in probabilities.items()}
    reports["repeat last"] = _report(actual, _onehot(y[rows - 1]))
    reports["always hold"] = _report(actual, _onehot(np.full(rows.size, HOLD)))
    return Backtest(rows=rows, actual=actual, reports=reports)
