"""The G-sec curve: shared loadings, NSS fits to market quotes, and the repo pass-through study.

Real-data anchors use FBIL's curves for 12 Oct 2026 (fixtures/fbil_curve_2026-10-12.json, as
published): its par curve must bootstrap back to its own zero-coupon curve, and an NSS fit to the
terminal's eleven quoted tenors must stay close to that official zero curve.
"""

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sovereign_engine.curves.base import par_yield
from sovereign_engine.curves.bootstrap import bootstrap_par_yields
from sovereign_engine.curves.nss import NelsonSiegelSvensson, Quote, fit_nss_quotes, quote_yields
from sovereign_engine.india.passthrough import (
    PassThrough,
    event_study,
    fit_passthrough,
    policy_changes,
)
from sovereign_engine.rates.loadings import expectations_loading, term_premium_loading
from sovereign_engine.rates.vasicek import Vasicek

FBIL: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "fbil_curve_2026-10-12.json").read_text("utf-8")
)
PAR = {float(t): v / 100 for t, v in FBIL["par"]}
ZERO = {float(t): v / 100 for t, v in FBIL["zero"]}
QUOTED = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 14.0, 20.0, 30.0)
"""The tenors the terminal stores from FBIL's par curve."""
CURVE = NelsonSiegelSvensson(0.07, -0.015, -0.02, 0.03, 1.5, 9.0)


def _semiannual(z: np.ndarray | float) -> np.ndarray:
    """Continuously compounded → semi-annually compounded."""
    return np.asarray(2 * np.expm1(np.asarray(z) / 2))


def _quotes(curve: NelsonSiegelSvensson) -> list[Quote]:
    bills = [Quote(d / 365, 0.0, "bill") for d in (91, 182, 364)]
    bonds = [Quote(float(t), 0.0, "par") for t in (2, 3, 5, 7, 10, 14, 20, 30)]
    rates = quote_yields(curve, bills + bonds)
    return [Quote(q.years, float(r), q.kind) for q, r in zip(bills + bonds, rates, strict=True)]


# ----------------------------------------------------------------------- loadings


def test_expectations_loading_is_the_vasicek_yield_loading() -> None:
    tenors = np.array([0.0, 0.25, 2.0, 10.0, 30.0])
    a = expectations_loading(tenors, 0.4)
    assert a[0] == 1.0
    assert np.all(np.diff(a) < 0)
    # Vasicek: y(τ) moves by B(τ)/τ per unit of r, B(τ) = (1 − e^(−aτ))/a.
    model = Vasicek(0.4, 0.05, 0.01)
    bump = 1e-6
    for t in tenors[1:]:
        before, after = model.bond_price(0.03, t), model.bond_price(0.03 + bump, t)
        move = (math.log(before) - math.log(after)) / t
        assert move / bump == pytest.approx(float(expectations_loading(t, 0.4)), rel=1e-6)


def test_term_premium_loading_rises_to_one_at_ten_years() -> None:
    t = np.array([0.25, 2.0, 10.0, 30.0])
    tp = term_premium_loading(t, 7.0)
    assert tp[2] == pytest.approx(1.0)
    assert np.all(np.diff(tp) > 0)
    assert float(term_premium_loading(0.0, 7.0)) == 0.0
    with pytest.raises(ValueError, match="positive"):
        term_premium_loading(t, 0.0)
    with pytest.raises(ValueError, match="positive"):
        expectations_loading(t, -1.0)


# ----------------------------------------------------------------------- NSS fit to quotes


def test_quote_yields_match_par_yield_and_bill_discounting() -> None:
    quotes = [Quote(91 / 365, 0.0, "bill"), Quote(10.0, 0.0, "par"), Quote(0.5, 0.0, "par")]
    bill, ten, half = quote_yields(CURVE, quotes)
    t = 91 / 365
    assert bill == pytest.approx((1 / float(CURVE.discount(t)) - 1) / t, rel=1e-12)
    assert ten == pytest.approx(par_yield(CURVE, 10.0), rel=1e-12)
    assert half == pytest.approx(par_yield(CURVE, 0.5), rel=1e-12)
    with pytest.raises(ValueError, match="whole number of coupon periods"):
        quote_yields(CURVE, [Quote(2.3, 0.0, "par")])


def test_fit_to_quotes_recovers_an_nss_curve() -> None:
    quotes = _quotes(CURVE)
    fit = fit_nss_quotes(quotes)
    assert fit.rmse_bp < 1e-3
    assert fit.n_points == len(quotes)
    t = np.linspace(0.25, 30, 60)
    assert np.max(np.abs(fit.curve.zero_rate(t) - CURVE.zero_rate(t))) * 1e4 < 0.05


def test_warm_start_follows_a_moved_curve() -> None:
    first = fit_nss_quotes(_quotes(CURVE))
    moved = NelsonSiegelSvensson(0.0725, -0.0155, -0.02, 0.031, 1.5, 9.0)
    quotes = _quotes(moved)
    warm = fit_nss_quotes(quotes, start=first)
    assert warm.rmse_bp < 0.01
    t = np.linspace(0.25, 30, 60)
    assert np.max(np.abs(warm.curve.zero_rate(t) - moved.zero_rate(t))) * 1e4 < 0.1


def test_fit_to_quotes_rejects_too_few_points() -> None:
    with pytest.raises(ValueError, match="six quotes"):
        fit_nss_quotes(_quotes(CURVE)[:5])


# ----------------------------------------------------------------------- FBIL anchors


def test_fbil_par_curve_bootstraps_to_fbils_zero_curve() -> None:
    """FBIL's conventions: semi-annual par yields, a simple 3-month yield, semi-annual zeros.

    Both curves are published to two decimals, so rounding accumulates along the bootstrap."""
    tenors = [0.25] + [t / 2 for t in range(1, 61)]
    curve = bootstrap_par_yields(tenors, [PAR[t] for t in tenors], freq=2)
    ours = _semiannual(curve.zero_rate(np.array(tenors)))
    errors = (ours - np.array([ZERO[t] for t in tenors])) * 1e4
    assert np.sqrt(np.mean(errors**2)) < 1.0  # 0.7 bp
    assert np.max(np.abs(errors)) < 2.5  # 2.0 bp


def test_nss_fit_to_the_quoted_tenors_tracks_fbils_zero_curve() -> None:
    """Eleven quoted tenors (bills simple, the rest par) against FBIL's full zero curve. NSS is
    smoother than FBIL's own fitted curve, so it misses its wiggles by several basis points."""
    quotes = [Quote(t, PAR[t], "bill" if t < 1 else "par") for t in QUOTED]
    fit = fit_nss_quotes(quotes)
    assert fit.rmse_bp < 4.0
    tenors = np.array([t / 4 for t in range(1, 121)])
    ours = _semiannual(fit.curve.zero_rate(tenors))
    errors = (ours - np.array([ZERO[float(t)] for t in tenors])) * 1e4
    assert np.sqrt(np.mean(errors**2)) < 10.0
    assert np.max(np.abs(errors)) < 20.0


# ----------------------------------------------------------------------- pass-through


def test_policy_changes_finds_the_moves() -> None:
    days = [date(2025, 6, 4) + timedelta(days=i) for i in range(5)]
    rates = [0.06, 0.06, 0.055, 0.055, 0.0575]
    (first, cut), (second, hike) = policy_changes(days, rates)
    assert (first, second) == (date(2025, 6, 6), date(2025, 6, 8))
    assert cut == pytest.approx(-0.005)
    assert hike == pytest.approx(0.0025)
    with pytest.raises(ValueError, match="increasing"):
        policy_changes(days[::-1], rates)
    with pytest.raises(ValueError, match="one rate per date"):
        policy_changes(days, rates[:3])


TENORS = np.array(QUOTED)
TRUE = PassThrough(kappa=0.5, gamma=0.3)


def _events(rng: np.random.Generator, k: int, noise: float) -> tuple[np.ndarray, np.ndarray]:
    """Repo changes, of which a random share is news, and the curve's response to the news."""
    changes = rng.choice([-0.005, -0.0025, 0.0025, 0.0035, 0.004, 0.005], size=k)
    surprise = changes * rng.uniform(0.1, 0.6, size=k)
    responses = surprise[:, None] * TRUE.beta(TENORS)[None, :]
    return changes, responses + rng.normal(0, noise, size=responses.shape)


def test_event_study_ratio_is_exact_without_noise() -> None:
    changes, responses = _events(np.random.default_rng(3), 12, 0.0)
    study = event_study(TENORS, changes, responses)
    assert study.relative[0] == 1.0
    np.testing.assert_allclose(study.relative, TRUE.beta(TENORS), atol=1e-12)
    # Same-day slopes on the actual change are much smaller: most changes were expected.
    assert np.all(study.day_beta < 0.7 * study.relative)
    assert np.all(study.relative_low <= study.relative + 1e-12)
    assert np.all(study.relative <= study.relative_high + 1e-12)


def test_fit_recovers_kappa_and_gamma() -> None:
    changes, responses = _events(np.random.default_rng(4), 12, 0.0)
    fit = fit_passthrough(event_study(TENORS, changes, responses))
    assert fit.curve.kappa == pytest.approx(TRUE.kappa, rel=1e-4)
    assert fit.curve.gamma == pytest.approx(TRUE.gamma, abs=1e-5)
    assert fit.rmse < 1e-6
    assert fit.half_life_years == pytest.approx(math.log(2) / 0.5, rel=1e-4)


def test_noisy_events_give_bands_that_cover_the_truth() -> None:
    changes, responses = _events(np.random.default_rng(5), 40, 0.0002)
    study = event_study(TENORS, changes, responses, draws=1000)
    truth = TRUE.beta(TENORS)
    inside = (study.relative_low <= truth) & (truth <= study.relative_high)
    assert inside.mean() >= 0.8
    fit = fit_passthrough(study, band_draws=100)
    lo, hi = fit.beta_10y_band
    assert lo < float(TRUE.beta(10.0)) < hi


def test_pass_through_is_one_at_the_anchor_and_decomposes() -> None:
    t = np.array([0.25, 1.0, 10.0, 30.0])
    beta = TRUE.beta(t)
    assert beta[0] == pytest.approx(1.0)
    np.testing.assert_allclose(TRUE.expectations(t) + TRUE.term_premium(t), beta)
    assert np.all(np.diff(TRUE.expectations(t)) < 0)
    assert np.all(np.diff(TRUE.term_premium(t)) > 0)


def test_event_study_rejects_unusable_input() -> None:
    changes, responses = _events(np.random.default_rng(6), 6, 0.0)
    with pytest.raises(ValueError, match="anchor tenor must be one of"):
        event_study(TENORS, changes, responses, anchor_tenor=0.3)
    with pytest.raises(ValueError, match="does not move with the repo rate"):
        event_study(TENORS, changes, -responses)
    with pytest.raises(ValueError, match="three events"):
        event_study(TENORS, changes[:2], responses[:2])
    with pytest.raises(ValueError, match="non-zero change"):
        event_study(TENORS, np.r_[0.0, changes[1:]], responses)
