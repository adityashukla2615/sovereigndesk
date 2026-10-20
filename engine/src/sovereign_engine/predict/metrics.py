"""How good a decision forecast is: hit rate, macro-F1, the confusion matrix, Brier score."""

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, IntArray, as_float_array

N_CLASSES = 5


def accuracy(actual: ArrayLike, predicted: ArrayLike) -> float:
    """Share of decisions called exactly.

    Equation:
        acc = (1/n) Σᵢ 1[ŷᵢ = yᵢ]
    """
    y, p = np.asarray(actual), np.asarray(predicted)
    if y.size == 0 or y.shape != p.shape:
        raise ValueError("need matching, non-empty actual and predicted classes")
    return float(np.mean(y == p))


def confusion_matrix(actual: ArrayLike, predicted: ArrayLike) -> IntArray:
    """Counts of actual class (rows) against predicted class (columns), all five classes.

    Equation:
        Cₐₚ = Σᵢ 1[yᵢ = a, ŷᵢ = p]
    """
    y, p = np.asarray(actual, dtype=np.int64), np.asarray(predicted, dtype=np.int64)
    out = np.zeros((N_CLASSES, N_CLASSES), dtype=np.int64)
    np.add.at(out, (y, p), 1)
    return out


def macro_f1(actual: ArrayLike, predicted: ArrayLike) -> float:
    """F1 averaged over the classes that occur (as actual or predicted), so a forecast that
    always says hold scores poorly however common holds are.

    Equation:
        F1ₖ = 2·TPₖ / (2·TPₖ + FPₖ + FNₖ),   macro-F1 = mean over k with TPₖ + FPₖ + FNₖ > 0
    """
    c = confusion_matrix(actual, predicted)
    tp = np.diag(c).astype(np.float64)
    fp = c.sum(axis=0) - tp
    fn = c.sum(axis=1) - tp
    seen = (tp + fp + fn) > 0
    return float(np.mean(2 * tp[seen] / (2 * tp[seen] + fp[seen] + fn[seen])))


def brier_score(actual: ArrayLike, probabilities: ArrayLike) -> float:
    """Multi-class Brier score (0 is perfect, 2 the worst).

    Equation:
        BS = (1/n) Σᵢ Σₖ (pᵢₖ − 1[yᵢ = k])²
    """
    y = np.asarray(actual, dtype=np.int64)
    p: FloatArray = np.atleast_2d(as_float_array(probabilities))
    if p.shape != (y.size, N_CLASSES):
        raise ValueError("need one row of five probabilities per decision")
    onehot = np.zeros_like(p)
    onehot[np.arange(y.size), y] = 1.0
    return float(np.mean(np.sum((p - onehot) ** 2, axis=1)))
