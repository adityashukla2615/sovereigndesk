"""Short-rate models: exact transitions against closed-form moments, closed-form bond prices
against Monte Carlo, and Hull–White's exact fit to the initial curve.

Monte Carlo checks allow four standard errors plus a small allowance for the trapezoidal
discretisation of ∫r dt, and use fixed seeds so they are deterministic.
"""

import math

import numpy as np
import pytest

from sovereign_engine._types import FloatArray
from sovereign_engine.curves.nss import NelsonSiegelSvensson
from sovereign_engine.curves.piecewise import LogLinearDiscountCurve
from sovereign_engine.rates.cir import CIR
from sovereign_engine.rates.corridor import (
    corridor_ou_step,
    from_logit,
    logit_sigma_for,
    to_logit,
)
from sovereign_engine.rates.hull_white import HullWhite
from sovereign_engine.rates.vasicek import Vasicek

# GSW parameters for 2026-10-08 (percent → decimals), a realistic smooth initial curve.
CURVE = NelsonSiegelSvensson(
    1.3508637666856e-14, 0.0395025548562066, 0.0470702914715823, 0.170607321206705, 1.96571, 15.83
)


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _mc_discount(short_rates: np.ndarray, dt: float) -> tuple[float, float]:
    """Mean and standard error of exp(−∫r dt) by the trapezoidal rule over each path."""
    integral = dt * (
        short_rates[:, 1:-1].sum(axis=1) + 0.5 * (short_rates[:, 0] + short_rates[:, -1])
    )
    discounts = np.exp(-integral)
    return float(discounts.mean()), float(discounts.std(ddof=1) / math.sqrt(discounts.size))


def _simulate(step, r0: float, n_paths: int, n_steps: int, dt: float, seed: int) -> np.ndarray:  # type: ignore[no-untyped-def]
    rng = _rng(seed)
    paths = np.empty((n_paths, n_steps + 1))
    paths[:, 0] = r0
    for k in range(n_steps):
        paths[:, k + 1] = step(paths[:, k], dt, rng)
    return paths


# ----------------------------------------------------------------------- Vasicek

VASICEK = Vasicek(a=0.3, b=0.045, sigma=0.012)


def test_vasicek_exact_step_moments() -> None:
    draws = VASICEK.step(np.full(400_000, 0.02), 2.0, _rng(1))
    se = math.sqrt(VASICEK.variance(2.0) / draws.size)
    assert draws.mean() == pytest.approx(float(VASICEK.mean(0.02, 2.0)), abs=4 * se)
    assert draws.var() == pytest.approx(VASICEK.variance(2.0), rel=0.01)


def test_vasicek_bond_price_closed_form_vs_monte_carlo() -> None:
    dt, years = 1 / 250, 3.0
    paths = _simulate(VASICEK.step, 0.02, 20_000, round(years / dt), dt, seed=2)
    mean, se = _mc_discount(paths, dt)
    assert mean == pytest.approx(float(VASICEK.bond_price(0.02, years)), abs=4 * se + 2e-5)


def test_vasicek_limits() -> None:
    assert float(VASICEK.bond_price(0.03, 1e-9)) == pytest.approx(1.0)
    long_run = VASICEK.b - VASICEK.sigma**2 / (2 * VASICEK.a**2)
    assert float(VASICEK.zero_rate(0.03, 2000.0)) == pytest.approx(long_run, abs=1e-4)


# ----------------------------------------------------------------------- CIR

CIR_MODEL = CIR(a=0.4, b=0.05, sigma=0.08)


def test_cir_feller() -> None:
    assert CIR_MODEL.feller()
    assert not CIR(a=0.1, b=0.02, sigma=0.2).feller()


def test_cir_exact_step_moments_and_positivity() -> None:
    draws = CIR_MODEL.step(np.full(400_000, 0.03), 1.5, _rng(3))
    variance = float(CIR_MODEL.variance(0.03, 1.5))
    assert draws.min() > 0
    assert draws.mean() == pytest.approx(
        float(CIR_MODEL.mean(0.03, 1.5)), abs=4 * math.sqrt(variance / draws.size)
    )
    assert draws.var() == pytest.approx(variance, rel=0.01)


def test_cir_stays_non_negative_without_feller() -> None:
    harsh = CIR(a=0.1, b=0.02, sigma=0.2)
    paths = _simulate(harsh.step, 0.01, 5_000, 200, 0.05, seed=4)
    assert paths.min() >= 0


def test_cir_bond_price_closed_form_vs_monte_carlo() -> None:
    dt, years = 1 / 250, 3.0
    paths = _simulate(CIR_MODEL.step, 0.03, 20_000, round(years / dt), dt, seed=5)
    mean, se = _mc_discount(paths, dt)
    assert mean == pytest.approx(float(CIR_MODEL.bond_price(0.03, years)), abs=4 * se + 2e-5)


def test_cir_long_rate_limit() -> None:
    h = math.sqrt(CIR_MODEL.a**2 + 2 * CIR_MODEL.sigma**2)
    long_run = 2 * CIR_MODEL.a * CIR_MODEL.b / (CIR_MODEL.a + h)
    assert float(CIR_MODEL.zero_rate(0.03, 5000.0)) == pytest.approx(long_run, abs=1e-4)


# ----------------------------------------------------------------------- Hull–White

HW = HullWhite(a=0.08, sigma=0.011, curve=CURVE)
MATURITIES = np.array([0.25, 1, 2, 5, 10, 20, 30.0])


@pytest.mark.parametrize(
    "curve",
    [
        CURVE,
        LogLinearDiscountCurve(
            times=np.array([1, 5, 30.0]), discounts=np.array([0.96, 0.82, 0.25])
        ),
    ],
)
def test_hull_white_reprices_initial_curve(
    curve: NelsonSiegelSvensson | LogLinearDiscountCurve,
) -> None:
    model = HullWhite(a=0.08, sigma=0.011, curve=curve)
    r0 = float(model.alpha(0.0))
    assert r0 == pytest.approx(float(curve.forward_rate(0.0)))
    assert (
        np.max(np.abs(model.bond_price(0.0, MATURITIES, r0) - curve.discount(MATURITIES))) < 1e-10
    )


def _bond_price_from_x(model: HullWhite, t: float, maturity: FloatArray, x: float) -> FloatArray:
    """Independent G1++ form (Brigo–Mercurio §4.2 with one factor) in terms of x(t)."""
    a, s = model.a, model.sigma

    def v(t0: float, t1: FloatArray | float) -> FloatArray:
        tau = np.asarray(t1, dtype=np.float64) - t0
        return np.asarray(
            s**2
            / a**2
            * (tau + 2 / a * np.exp(-a * tau) - 1 / (2 * a) * np.exp(-2 * a * tau) - 3 / (2 * a)),
            dtype=np.float64,
        )

    ratio = model.curve.discount(maturity) / float(model.curve.discount(t))
    b = model.loading(t, maturity)
    exponent = 0.5 * (v(t, maturity) - v(0.0, maturity) + v(0.0, t)) - b * x
    return np.asarray(ratio * np.exp(exponent), dtype=np.float64)


@pytest.mark.parametrize("x", [-0.02, 0.0, 0.013])
def test_hull_white_closed_forms_agree(x: float) -> None:
    t = 1.5
    r = float(HW.short_rate(x, t))
    assert np.allclose(
        HW.bond_price(t, t + MATURITIES, r),
        _bond_price_from_x(HW, t, t + MATURITIES, x),
        rtol=1e-12,
    )


def test_hull_white_theta_drives_alpha() -> None:
    # E[r(t)] = α(t) must solve dα/dt = θ(t) − a·α(t).
    t, h = np.array([0.5, 2.0, 7.0, 15.0]), 1e-5
    slope = (HW.alpha(t + h) - HW.alpha(t - h)) / (2 * h)
    assert np.allclose(slope, HW.theta(t) - HW.a * HW.alpha(t), atol=1e-8)


def test_hull_white_monte_carlo_reprices_curve() -> None:
    dt, years = 1 / 250, 5.0
    n_steps = round(years / dt)
    rng = _rng(6)
    x = np.zeros(20_000)
    rates = np.empty((x.size, n_steps + 1))
    rates[:, 0] = HW.short_rate(x, 0.0)
    for k in range(n_steps):
        x = HW.step_x(x, dt, rng)
        rates[:, k + 1] = HW.short_rate(x, (k + 1) * dt)
    mean, se = _mc_discount(rates, dt)
    assert mean == pytest.approx(float(CURVE.discount(years)), abs=4 * se + 2e-5)
    assert rates[:, -1].mean() == pytest.approx(
        float(HW.alpha(years)), abs=4 * rates[:, -1].std() / math.sqrt(x.size)
    )


def test_hull_white_curve_shape() -> None:
    curves = HW.zero_rates(1.0, MATURITIES, np.array([0.03, 0.04, 0.05]))
    assert curves.shape == (3, MATURITIES.size)
    assert np.all(np.diff(curves[:, 0]) > 0)  # higher short rate, higher short-end yields


# ----------------------------------------------------------------------- corridor (logit-OU)

SDF, MSF = 0.0525, 0.0575


def test_logit_round_trip() -> None:
    r = np.array([0.0526, 0.055, 0.0574])
    assert np.allclose(from_logit(to_logit(r, SDF, MSF), SDF, MSF), r, rtol=1e-12)


def test_corridor_never_breached_even_under_violent_shocks() -> None:
    rng = _rng(7)
    r = np.full(1_000, 0.055)
    for step in range(10_000):
        upper = MSF + (0.0025 if step > 5_000 else 0.0)  # corridor shifts up mid-run
        r = corridor_ou_step(
            r,
            lower=SDF,
            upper=upper,
            target=(SDF + upper) / 2,
            kappa=50.0,
            sigma_x=40.0,
            dt=1 / 1440,
            rng=rng,
        )
        assert np.all((r > SDF) & (r < upper))


def test_corridor_median_reverts_to_target() -> None:
    target = 0.0545
    rng = _rng(8)
    r = np.full(40_000, 0.0570)
    for _ in range(200):
        r = corridor_ou_step(
            r, lower=SDF, upper=MSF, target=target, kappa=20.0, sigma_x=1.5, dt=0.01, rng=rng
        )
    assert float(np.median(r)) == pytest.approx(target, abs=2e-5)


def test_logit_sigma_matches_local_rate_volatility() -> None:
    target, sigma_r, dt = 0.0545, 0.0008, 1e-4
    sigma_x = logit_sigma_for(sigma_r, SDF, MSF, target)
    r = corridor_ou_step(
        np.full(200_000, target),
        lower=SDF,
        upper=MSF,
        target=target,
        kappa=5.0,
        sigma_x=sigma_x,
        dt=dt,
        rng=_rng(9),
    )
    assert r.std() / math.sqrt(dt) == pytest.approx(sigma_r, rel=0.02)


def test_corridor_validation() -> None:
    with pytest.raises(ValueError, match="strictly inside"):
        logit_sigma_for(0.001, SDF, MSF, MSF)
    with pytest.raises(ValueError, match="upper > lower"):
        to_logit(0.05, MSF, SDF)
