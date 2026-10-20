"""The MPC predictor's building blocks: classes, the HP filter, the Taylor baseline, the two
learned models (the ordered logit checked against statsmodels) and the walk-forward backtest."""

import warnings

import numpy as np
import pytest
from statsmodels.miscmodels.ordinal_model import OrderedModel

from sovereign_engine.predict import (
    HOLD,
    TaylorBaseline,
    TaylorRule,
    accuracy,
    brier_score,
    component_weights,
    confusion_matrix,
    decision_class,
    exclusion_index,
    fit_boosted,
    fit_ordered_logit,
    hp_one_sided,
    hp_trend,
    macro_f1,
    walk_forward,
)


def test_decision_classes_split_at_one_policy_step() -> None:
    changes = [-0.0075, -0.0035, -0.0025, -0.0005, 0.0, 0.0025, 0.0035, 0.005]
    assert list(decision_class(changes)) == [0, 0, 1, 1, 2, 3, 4, 4]


def test_hp_trend_limits_and_the_one_sided_end_point() -> None:
    rng = np.random.default_rng(0)
    y = np.cumsum(rng.normal(0, 1, 40)) + np.linspace(0, 10, 40)
    np.testing.assert_allclose(hp_trend(y, 0.0), y, atol=1e-10)
    line = 3.0 + 0.5 * np.arange(30)
    np.testing.assert_allclose(hp_trend(line, 1600.0), line, atol=1e-8)  # lines pass through
    one = hp_one_sided(y, 1600.0, min_obs=8)
    assert np.all(np.isnan(one[:7]))
    for t in (7, 20, 39):
        assert one[t] == pytest.approx(hp_trend(y[: t + 1], 1600.0)[-1])
    assert one[-1] == pytest.approx(hp_trend(y, 1600.0)[-1])  # the last point needs no future
    with pytest.raises(ValueError, match="three observations"):
        hp_trend([1.0, 2.0])


def test_taylor_rule_and_its_stepwise_baseline() -> None:
    rule = TaylorRule(r_star=0.015)
    assert float(rule.prescribed(0.06, 0.01)) == pytest.approx(0.015 + 0.06 + 0.01 + 0.005)
    base = TaylorBaseline(rule)
    # prescribed 8.5% against a 6% repo: a quarter of the 2.5-point gap is 62.5 bp → capped at 50
    assert float(base.change(0.06, 0.06, 0.01)) == pytest.approx(0.005)
    # inflation on target, no gap: i* = 5.5%; repo 6% → a quarter of −50 bp rounds to −25 bp
    assert float(base.change(0.06, 0.04, 0.0)) == pytest.approx(-0.0025)
    assert float(base.change(0.055, 0.04, 0.0)) == 0.0
    proba = base.predict_proba([0.06, 0.055], [0.06, 0.04], [0.01, 0.0])
    np.testing.assert_array_equal(proba, [[0, 0, 0, 0, 1], [0, 0, 1, 0, 0]])


def _ordinal(n: int, seed: int, noise: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 3))
    latent = x @ np.array([1.2, -0.7, 0.4]) + noise * rng.logistic(size=n)
    y = np.digitize(latent, [-2.0, -0.5, 1.0, 2.5])
    return x, y


def test_ordered_logit_is_statsmodels_likelihood_when_unpenalised() -> None:
    x, y = _ordinal(600, 1)
    ours = fit_ordered_logit(x, y, l2=0.0)
    xs = (x - x.mean(axis=0)) / x.std(axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        reference = OrderedModel(y, xs, distr="logit").fit(method="bfgs", disp=False, maxiter=5000)
    np.testing.assert_allclose(ours.beta, reference.params[:3], atol=2e-4)
    np.testing.assert_allclose(
        ours.predict_proba(x)[:, : len(set(y))], reference.predict(xs), atol=2e-4
    )


def test_ordered_logit_penalty_unseen_classes_and_one_class() -> None:
    x, y = _ordinal(200, 2)
    loose, tight = fit_ordered_logit(x, y, l2=0.0), fit_ordered_logit(x, y, l2=50.0)
    assert np.linalg.norm(tight.beta) < np.linalg.norm(loose.beta)
    middle = y[(y >= 1) & (y <= 3)]
    proba = fit_ordered_logit(x[(y >= 1) & (y <= 3)], middle).predict_proba(x[:5])
    np.testing.assert_allclose(proba[:, [0, 4]], 0.0)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0)
    single = fit_ordered_logit(x[:10], np.full(10, HOLD)).predict_proba(x[:3])
    np.testing.assert_array_equal(single, np.tile([0, 0, 1, 0, 0], (3, 1)))


def test_boosted_trees_learn_a_rule_and_keep_unseen_classes_at_zero() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(300, 2))
    y = np.where(x[:, 0] > 0.5, 3, np.where(x[:, 0] < -0.5, 1, HOLD))
    model = fit_boosted(x, y)
    proba = model.predict_proba(x)
    assert accuracy(y, np.argmax(proba, axis=1)) > 0.9
    np.testing.assert_allclose(proba[:, [0, 4]], 0.0)
    x[::7, 1] = np.nan  # XGBoost routes missing values itself
    assert np.all(np.isfinite(model.predict_proba(x)))
    single = fit_boosted(x[:5], np.full(5, 3)).predict_proba(x[:2])
    np.testing.assert_array_equal(single, np.tile([0, 0, 0, 1, 0], (2, 1)))


def test_metrics() -> None:
    actual = np.array([2, 2, 2, 1, 3])
    hold = np.full(5, HOLD)
    assert accuracy(actual, hold) == pytest.approx(0.6)
    # Always holding scores F1 0.75 on holds and 0 on the cut and the hike that occurred.
    assert macro_f1(actual, hold) == pytest.approx(0.75 / 3)
    assert macro_f1(actual, actual) == 1.0
    c = confusion_matrix(actual, hold)
    assert (int(c[2, 2]), int(c[1, 2]), int(c.sum())) == (3, 1, 5)
    perfect = np.eye(5)[actual]
    assert brier_score(actual, perfect) == 0.0
    assert brier_score(actual, np.full((5, 5), 0.2)) == pytest.approx(0.8)


def test_walk_forward_fits_only_on_the_past() -> None:
    x, y = _ordinal(80, 4, noise=0.3)
    seen: list[int] = []

    def fitter(train_x: np.ndarray, train_y: np.ndarray):  # type: ignore[no-untyped-def]
        seen.append(len(train_y))
        return fit_ordered_logit(train_x, train_y)

    result = walk_forward(x, y, {"logit": fitter}, start=40)
    assert seen == list(range(40, 80))
    assert list(result.rows) == list(range(40, 80))
    assert set(result.reports) == {"logit", "repeat last", "always hold"}
    logit = result.reports["logit"]
    assert logit.probabilities.shape == (40, 5)
    assert logit.accuracy > result.reports["always hold"].accuracy
    assert logit.brier < result.reports["repeat last"].brier
    np.testing.assert_array_equal(result.reports["repeat last"].predicted, y[39:79])
    with pytest.raises(ValueError, match="start"):
        walk_forward(x, y, {"logit": fitter}, start=0)


def test_weights_are_recovered_from_a_laspeyres_index_and_core_excludes_them() -> None:
    rng = np.random.default_rng(5)
    months = 60
    components = 100 * np.exp(np.cumsum(rng.normal(0.004, 0.01, size=(months, 4)), axis=0))
    weights = np.array([0.46, 0.07, 0.17, 0.30])
    total = np.round(components @ weights, 1)  # published to one decimal
    estimated, rmse = component_weights(total, np.round(components, 1))
    np.testing.assert_allclose(estimated, weights, atol=0.01)
    assert rmse < 0.1
    core = exclusion_index(total, components[:, :2], weights[:2])
    expected = components[:, 2:] @ (weights[2:] / weights[2:].sum())
    np.testing.assert_allclose(core, expected, atol=0.2)
    with pytest.raises(ValueError, match="as many periods"):
        component_weights(total[:3], components[:3])
