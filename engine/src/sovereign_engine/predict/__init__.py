"""Predicting RBI's next policy decision: decision classes, a one-sided HP filter for the output
gap, the Taylor-rule baseline, an ordered logit and gradient boosting, and walk-forward
backtests with their metrics."""

from sovereign_engine.predict.backtest import Backtest, ModelReport, walk_forward
from sovereign_engine.predict.classes import CLASSES, HOLD, decision_class
from sovereign_engine.predict.filters import hp_one_sided, hp_trend
from sovereign_engine.predict.inflation import component_weights, exclusion_index
from sovereign_engine.predict.metrics import accuracy, brier_score, confusion_matrix, macro_f1
from sovereign_engine.predict.models import (
    BoostedClassifier,
    OrderedLogit,
    fit_boosted,
    fit_ordered_logit,
)
from sovereign_engine.predict.taylor import TaylorBaseline, TaylorRule

__all__ = [
    "CLASSES",
    "HOLD",
    "Backtest",
    "BoostedClassifier",
    "ModelReport",
    "OrderedLogit",
    "TaylorBaseline",
    "TaylorRule",
    "accuracy",
    "brier_score",
    "component_weights",
    "confusion_matrix",
    "decision_class",
    "exclusion_index",
    "fit_boosted",
    "fit_ordered_logit",
    "hp_one_sided",
    "hp_trend",
    "macro_f1",
    "walk_forward",
]
