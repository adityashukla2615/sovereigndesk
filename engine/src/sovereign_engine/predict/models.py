"""The two learned predictors: an ordered logit and gradient-boosted trees.

Both see only the decision classes present in their training window and spread their
probabilities over those; the classes they have not seen get zero. Features are standardised
with the training window's means and s.d.s.

* Ordered logit: the cumulative-logit model of statsmodels' ``OrderedModel`` (one slope per
  feature, increasing cut-points), with an L2 penalty on the slopes. With a few dozen decisions
  and a class or two that occur only a handful of times, unpenalised estimates diverge under
  separation; at λ = 0 this is exactly the statsmodels likelihood (tested against it).
* Boosted trees: XGBoost's multi-class softmax with shallow trees, shrinkage, subsampling and
  an L2 leaf penalty, the regularisation small samples need. Missing features are handled by
  XGBoost's default split directions.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from xgboost import XGBClassifier

from sovereign_engine._types import ArrayLike, FloatArray, IntArray, as_float_array

N_CLASSES = 5


def _standardise(x: FloatArray) -> tuple[FloatArray, FloatArray]:
    means = np.nanmean(x, axis=0)
    sds = np.nanstd(x, axis=0)
    return means, np.where(sds > 0, sds, 1.0)


def _expand(proba: FloatArray, present: IntArray) -> FloatArray:
    out = np.zeros((proba.shape[0], N_CLASSES))
    out[:, present] = proba
    return out


@dataclass(frozen=True, slots=True)
class OrderedLogit:
    present: IntArray
    """The classes seen in training, ascending."""
    means: FloatArray
    sds: FloatArray
    beta: FloatArray
    """Slopes on the standardised features."""
    cuts: FloatArray
    """Cut-points θ₀ < θ₁ < … between consecutive present classes."""

    def predict_proba(self, features: ArrayLike) -> FloatArray:
        """Class probabilities (one row per observation, five columns).

        Equation:
            P(y ≤ j | x) = σ(θⱼ − x̃ᵀβ),   P(y = j) = P(y ≤ j) − P(y ≤ j − 1),   x̃ = (x − μ)/s
        """
        x = (np.atleast_2d(as_float_array(features)) - self.means) / self.sds
        x = np.nan_to_num(x)
        if self.cuts.size == 0:
            return _expand(np.ones((x.shape[0], 1)), self.present)
        cdf = expit(self.cuts[None, :] - (x @ self.beta)[:, None])
        bounds = np.column_stack((np.zeros(x.shape[0]), cdf, np.ones(x.shape[0])))
        return _expand(np.clip(np.diff(bounds, axis=1), 0.0, 1.0), self.present)


def _cuts(params: FloatArray) -> FloatArray:
    return np.asarray(params[0] + np.concatenate(([0.0], np.cumsum(np.exp(params[1:])))))


def fit_ordered_logit(features: ArrayLike, classes: ArrayLike, *, l2: float = 1.0) -> OrderedLogit:
    """Penalised maximum likelihood for the cumulative logit (analytic gradient, L-BFGS).

    Equation:
        min_{β, c}  −Σᵢ log[σ(θ_{yᵢ} − x̃ᵢᵀβ) − σ(θ_{yᵢ−1} − x̃ᵢᵀβ)] + (λ/2)·‖β‖²
        θ₀ = c₀,  θⱼ = θⱼ₋₁ + e^{cⱼ}  (so θ is increasing),  θ₋₁ = −∞,  θ_{m−1} = +∞
    """
    x_raw = np.atleast_2d(as_float_array(features))
    y_raw = np.asarray(classes, dtype=np.int64)
    if x_raw.shape[0] != y_raw.size or y_raw.size == 0:
        raise ValueError("need one class per row of features")
    present = np.unique(y_raw)
    means, sds = _standardise(x_raw)
    x = np.nan_to_num((x_raw - means) / sds)
    m, k = present.size, x.shape[1]
    if m == 1:
        return OrderedLogit(present, means, sds, np.zeros(k), np.zeros(0))
    y = np.searchsorted(present, y_raw)
    n = y.size

    def objective(params: FloatArray) -> tuple[float, FloatArray]:
        beta, cut_params = params[:k], params[k:]
        theta = _cuts(cut_params)
        eta = x @ beta
        upper = np.where(y < m - 1, theta[np.minimum(y, m - 2)], np.inf)
        lower = np.where(y > 0, theta[np.maximum(y - 1, 0)], -np.inf)
        f_up, f_lo = expit(upper - eta), expit(lower - eta)
        d_up, d_lo = f_up * (1 - f_up), f_lo * (1 - f_lo)
        p = np.maximum(f_up - f_lo, 1e-300)
        loss = -float(np.sum(np.log(p))) + 0.5 * l2 * float(beta @ beta)
        # ∂(−log p)/∂β = x·(d_up − d_lo)/p;  ∂(−log p)/∂θⱼ = −d_up/p (j = y) or +d_lo/p (j = y−1)
        grad_beta = x.T @ ((d_up - d_lo) / p) + l2 * beta
        grad_theta = np.zeros(m - 1)
        np.add.at(grad_theta, np.minimum(y, m - 2)[y < m - 1], -(d_up / p)[y < m - 1])
        np.add.at(grad_theta, np.maximum(y - 1, 0)[y > 0], (d_lo / p)[y > 0])
        # θⱼ = c₀ + Σ_{l≤j} e^{c_l}: ∂θⱼ/∂c₀ = 1, ∂θⱼ/∂c_l = e^{c_l} for 1 ≤ l ≤ j
        exp_c = np.exp(cut_params[1:])
        tail = np.cumsum(grad_theta[::-1])[::-1]
        grad_cuts = np.concatenate(([tail[0]], tail[1:] * exp_c))
        return loss, np.concatenate((grad_beta, grad_cuts))

    shares = np.cumsum(np.bincount(y, minlength=m))[:-1] / n
    start_theta = np.log(shares / (1 - shares))
    start = np.concatenate(
        (np.zeros(k), [start_theta[0]], np.log(np.maximum(np.diff(start_theta), 1e-3)))
    )
    sol = minimize(objective, start, jac=True, method="L-BFGS-B", options={"maxiter": 2000})
    params = np.asarray(sol.x, dtype=np.float64)
    return OrderedLogit(present, means, sds, params[:k], _cuts(params[k:]))


@dataclass(frozen=True, slots=True)
class BoostedClassifier:
    present: IntArray
    model: Any
    """The fitted XGBoost classifier (None when training saw one class)."""

    def predict_proba(self, features: ArrayLike) -> FloatArray:
        """Class probabilities (one row per observation, five columns).

        Equation:
            pₖ(x) = softmax_k(Σ_trees f_{t,k}(x))   over the classes seen in training
        """
        x = np.atleast_2d(as_float_array(features))
        if self.model is None:
            return _expand(np.ones((x.shape[0], 1)), self.present)
        # XGBoost computes in float32; renormalise in float64 so each row sums to one.
        raw = np.asarray(self.model.predict_proba(x), dtype=np.float64)
        return _expand(raw / raw.sum(axis=1, keepdims=True), self.present)


BOOST_PARAMS: dict[str, Any] = {
    "n_estimators": 200,
    "max_depth": 2,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 2.0,
    "reg_lambda": 5.0,
    "tree_method": "hist",
    "random_state": 0,
    "n_jobs": 1,
}
"""Small, shallow and shrunk: the regularisation a few dozen decisions call for."""


def fit_boosted(
    features: ArrayLike, classes: ArrayLike, *, params: dict[str, Any] | None = None
) -> BoostedClassifier:
    """Gradient-boosted trees on the decision classes seen in training.

    Equation:
        min_f Σᵢ −log softmax_{yᵢ}(F(xᵢ)) + Σ_trees (γ·T + ½λ‖w‖²),   F = Σ_t η·f_t
    """
    x = np.atleast_2d(as_float_array(features))
    y_raw = np.asarray(classes, dtype=np.int64)
    if x.shape[0] != y_raw.size or y_raw.size == 0:
        raise ValueError("need one class per row of features")
    present = np.unique(y_raw)
    if present.size == 1:
        return BoostedClassifier(present, None)
    model = XGBClassifier(**(BOOST_PARAMS | (params or {})))
    model.fit(x, np.searchsorted(present, y_raw))
    return BoostedClassifier(present, model)
