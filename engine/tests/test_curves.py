import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sovereign_engine.curves.base import forward_between, par_yield
from sovereign_engine.curves.bootstrap import bootstrap_par_yields
from sovereign_engine.curves.nss import NelsonSiegelSvensson, fit_nss
from sovereign_engine.curves.piecewise import LogLinearDiscountCurve

GSW: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "gsw_nss.json").read_text("utf-8")
)
YEARS = np.arange(1, 31, dtype=np.float64)


def _gsw_curve(row: dict[str, Any]) -> NelsonSiegelSvensson:
    """The Fed's published GSW parameters, converted from percent to decimals."""
    b = [float(row[f"BETA{i}"]) / 100 for i in range(4)]
    return NelsonSiegelSvensson(b[0], b[1], b[2], b[3], float(row["TAU1"]), float(row["TAU2"]))


def _published(row: dict[str, Any], series: str) -> tuple[np.ndarray, np.ndarray]:
    pairs = [(float(n), float(v)) for n, v in row[series].items() if v not in ("", "NA")]
    years, values = zip(*pairs, strict=True)
    return np.array(years), np.array(values) / 100


# ----------------------------------------------------------------------- NSS vs the Fed (GSW)


@pytest.mark.parametrize("row", GSW["rows"], ids=lambda r: r["Date"])
def test_nss_reproduces_published_gsw_yields(row: dict[str, Any]) -> None:
    """GSW publish zero (SVENY), forward (SVENF) and par (SVENPY) yields to four decimals in %."""
    curve = _gsw_curve(row)
    half_unit = 0.5e-4 / 100 + 1e-12
    years, zeros = _published(row, "SVENY")
    assert np.max(np.abs(curve.zero_rate(years) - zeros)) <= half_unit
    years, forwards = _published(row, "SVENF")
    assert np.max(np.abs(curve.forward_rate(years) - forwards)) <= half_unit
    years, pars = _published(row, "SVENPY")
    ours = np.array([par_yield(curve, float(n)) for n in years])
    assert np.max(np.abs(ours - pars)) <= half_unit


def test_nss_forward_slope_and_discount() -> None:
    curve = _gsw_curve(GSW["rows"][0])
    t, h = np.array([0.25, 1.0, 7.5, 25.0]), 1e-6
    numeric = (curve.forward_rate(t + h) - curve.forward_rate(t - h)) / (2 * h)
    assert np.allclose(curve.forward_slope(t), numeric, atol=1e-8)
    assert np.allclose(curve.discount(t), np.exp(-curve.zero_rate(t) * t))
    # Short end: z(0) = f(0) = β₀ + β₁.
    assert float(curve.zero_rate(0.0)) == pytest.approx(curve.beta0 + curve.beta1)
    assert float(curve.forward_rate(0.0)) == pytest.approx(curve.beta0 + curve.beta1)


@pytest.mark.parametrize("row", GSW["rows"], ids=lambda r: r["Date"])
def test_fit_recovers_gsw_curve(row: dict[str, Any]) -> None:
    truth = _gsw_curve(row)
    fit = fit_nss(YEARS, truth.zero_rate(YEARS))
    assert fit.max_abs_error_bp < 0.01
    # It also fits the published, rounded yields to within their rounding.
    years, published = _published(row, "SVENY")
    assert fit_nss(years, published).rmse_bp < 0.01


def test_tau_derivatives_match_finite_differences() -> None:
    from sovereign_engine.curves.nss import _level_and_hump, _level_hump_tau_derivatives

    t = np.array([1e-6, 0.25, 1.0, 5.0, 30.0])
    for tau in (0.3, 2.0, 15.0):
        h = 1e-6 * tau
        dl, dh = _level_hump_tau_derivatives(t, tau)
        (l_up, h_up), (l_dn, h_dn) = _level_and_hump(t, tau + h), _level_and_hump(t, tau - h)
        assert np.allclose(dl, (l_up - l_dn) / (2 * h), atol=1e-7)
        assert np.allclose(dh, (h_up - h_dn) / (2 * h), atol=1e-7)


def test_fit_respects_constraints() -> None:
    # An inverted, noisy curve: constraints must hold however the optimiser wanders.
    t = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30.0])
    z = np.array([5.3, 5.25, 5.05, 4.7, 4.5, 4.3, 4.3, 4.35, 4.6, 4.5]) / 100
    fit = fit_nss(t, z + np.random.default_rng(7).normal(0, 2e-4, t.size))
    c = fit.curve
    assert c.beta0 >= 0
    assert c.beta0 + c.beta1 >= 0
    assert 0 < c.tau1 < c.tau2
    assert fit.rmse_bp < 5


def test_fit_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="six"):
        fit_nss([1, 2, 3], [0.04, 0.041, 0.042])
    with pytest.raises(ValueError, match="weights"):
        fit_nss(YEARS, np.full(30, 0.04), weights=-np.ones(30))


# ----------------------------------------------------------------------- log-linear curve


def test_log_linear_curve_basics() -> None:
    curve = LogLinearDiscountCurve(
        times=np.array([1.0, 2.0, 5.0]), discounts=np.array([0.96, 0.92, 0.80])
    )
    assert np.allclose(curve.discount([1.0, 2.0, 5.0]), [0.96, 0.92, 0.80])
    assert float(curve.discount(0.0)) == 1.0
    f1, f2, f3 = -np.log(0.96), np.log(0.96 / 0.92), np.log(0.92 / 0.80) / 3
    assert np.allclose(curve.forward_rate([0.5, 1.0, 1.5, 2.0, 4.0, 9.0]), [f1, f1, f2, f2, f3, f3])
    assert float(curve.zero_rate(0.0)) == pytest.approx(f1)
    assert float(curve.zero_rate(0.5)) == pytest.approx(f1)  # flat forward before the first knot
    assert float(curve.discount(7.0)) == pytest.approx(
        0.80 * np.exp(-f3 * 2)
    )  # flat beyond the last
    assert forward_between(curve, 2.0, 5.0) == pytest.approx(f3)


def test_log_linear_curve_validation() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        LogLinearDiscountCurve(times=np.array([2.0, 1.0]), discounts=np.array([0.9, 0.95]))
    with pytest.raises(ValueError, match="positive"):
        LogLinearDiscountCurve(times=np.array([1.0]), discounts=np.array([0.0]))


# ----------------------------------------------------------------------- bootstrap

TENORS = np.array([1, 1.5, 2, 3, 4, 6, 12, 24, 36, 60, 84, 120, 240, 360]) / 12
PARS = (
    np.array([4.20, 4.18, 4.15, 4.10, 4.05, 3.95, 3.80, 3.62, 3.60, 3.70, 3.85, 4.05, 4.55, 4.60])
    / 100
)


def test_bootstrap_reprices_every_par_bond() -> None:
    curve = bootstrap_par_yields(TENORS, PARS)
    grid = np.arange(1, 61) / 2
    for t in grid:
        assert par_yield(curve, float(t)) == pytest.approx(
            float(np.interp(t, TENORS, PARS)), abs=1e-14
        )
    for t, y in zip(TENORS[TENORS < 0.5], PARS[TENORS < 0.5], strict=True):
        assert float(curve.discount(t)) == pytest.approx(1 / (1 + y * t), rel=1e-14)


def test_flat_par_curve_gives_flat_zeros() -> None:
    y = 0.045
    curve = bootstrap_par_yields(np.array([0.5, 30.0]), np.array([y, y]))
    grid = np.arange(1, 61) / 2
    assert np.allclose(curve.discount(grid), (1 + y / 2) ** (-2 * grid), rtol=1e-13)


def test_bootstrap_validation() -> None:
    with pytest.raises(ValueError, match="whole number of coupon periods"):
        bootstrap_par_yields(np.array([0.5, 2.3]), np.array([0.04, 0.04]))
    with pytest.raises(ValueError, match="non-positive"):
        bootstrap_par_yields(np.array([0.5, 1.0, 30.0]), np.array([0.04, 0.04, 2.5]))
