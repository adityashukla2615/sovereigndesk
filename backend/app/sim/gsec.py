"""The live G-sec curve: FBIL's close moved by repo surprises and two mean-reverting factors.

The 91/182/364-day points are the money market's T-bill yields (FBIL's benchmarks plus the
liquidity spread, repo changes passed through by β(τ)). Each coupon tenor is FBIL's par yield
plus

    β(τ)·Δrepo + A(τ; κ)·x + T(τ)·u

where Δrepo is the repo change since FBIL's publication, β the event-study pass-through, and x
(expectations) and u (term premium) are factors whose daily shocks have the s.d. and
correlation measured on FBIL's history. The factors move with the call market's rounds
(09:15-19:00 IST on business days) and revert to zero over months, so without news the curve
drifts back to FBIL's close plus the policy moves. Every update refits NSS to the points, warm
started from the previous fit.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from app.data.catalog import FBIL_GSEC_TENORS
from app.sim.gsec_anchors import BILL_DAYS, COUPON_TENORS, TBILL_OF, GsecAnchors, quotes_of
from sovereign_engine.curves.nss import NelsonSiegelSvensson, NssFit, fit_nss_quotes
from sovereign_engine.rates.loadings import expectations_loading, term_premium_loading

PANEL_GRID = np.round(np.concatenate(([0.25, 0.5, 0.75], np.arange(1.0, 30.5, 0.5))), 4)
"""Maturities the panel draws β(τ) and the fitted curve on."""


@dataclass(frozen=True, slots=True)
class GsecParams:
    """Parameters that are assumptions rather than fits (listed in ASSUMPTIONS.md)."""

    factor_half_life_days: float = 125.0
    """Half-life of the two curve factors, in business days (about six months)."""


@dataclass(frozen=True, slots=True)
class CurveClose:
    day: date
    par: dict[str, float]


def nss_params(curve: NelsonSiegelSvensson) -> dict[str, float]:
    return {
        "beta0": curve.beta0,
        "beta1": curve.beta1,
        "beta2": curve.beta2,
        "beta3": curve.beta3,
        "tau1": curve.tau1,
        "tau2": curve.tau2,
    }


class GsecCurve:
    def __init__(
        self, anchors: GsecAnchors, rng: np.random.Generator, params: GsecParams | None = None
    ) -> None:
        self.anchors = anchors
        self.params = params or GsecParams()
        self.rng = rng
        curve = anchors.passthrough.curve
        years = np.array(list(FBIL_GSEC_TENORS.values()))
        self.betas = dict(zip(FBIL_GSEC_TENORS, (float(b) for b in curve.beta(years)), strict=True))
        """Par-yield change per unit of repo surprise, by tenor."""
        coupon = np.array([FBIL_GSEC_TENORS[t] for t in COUPON_TENORS])
        level = expectations_loading(coupon, curve.kappa)
        self._level = {t: float(v) for t, v in zip(COUPON_TENORS, level, strict=True)}
        tp = term_premium_loading(coupon, curve.scale)
        self._tp = {t: float(v) for t, v in zip(COUPON_TENORS, tp, strict=True)}
        f = anchors.factors
        covariance = np.array(
            [
                [f.level_sd**2, f.correlation * f.level_sd * f.tp_sd],
                [f.correlation * f.level_sd * f.tp_sd, f.tp_sd**2],
            ]
        )
        self._chol = np.linalg.cholesky(covariance + 1e-18 * np.eye(2))
        self.level = 0.0
        """Expectations factor (decimal; loading one at the front end)."""
        self.tp = 0.0
        """Term-premium factor (decimal; loading one at 10 years)."""
        self.repo_shift = 0.0
        self.points: dict[str, float] = dict(anchors.close)
        self.fit: NssFit = anchors.fit
        self.history: list[CurveClose] = []

    def shift_term_premium(self, change: float) -> None:
        """Move the term-premium factor (decimal at 10 years), e.g. by the US 10Y's spillover;
        it then decays like any other move of the factor."""
        self.tp += change

    def tbill_beta(self, years: float) -> float:
        """β at a bill maturity, for the money market's T-bills."""
        return float(self.anchors.passthrough.curve.beta(years))

    def update(self, tbills: dict[str, float], repo_shift: float) -> None:
        """New market points from the money market's T-bills and the repo change since FBIL's
        publication; refits NSS when any point moved."""
        self.repo_shift = repo_shift
        points = {t: tbills[TBILL_OF[t]] for t in BILL_DAYS}
        for t in COUPON_TENORS:
            points[t] = (
                self.anchors.par[t]
                + self.betas[t] * repo_shift
                + self._level[t] * self.level
                + self._tp[t] * self.tp
            )
        ordered = {t: points[t] for t in FBIL_GSEC_TENORS}
        if ordered != self.points:
            self.points = ordered
            self.fit = fit_nss_quotes(quotes_of(ordered), start=self.fit)

    def step(self, days: float) -> None:
        """Advance both factors by ``days`` business days: an exact OU step with the fitted
        daily covariance."""
        k = math.log(2) / self.params.factor_half_life_days
        decay = math.exp(-k * days)
        scale = math.sqrt(-math.expm1(-2 * k * days) / (2 * k))
        shock = self._chol @ self.rng.standard_normal(2) * scale
        self.level = self.level * decay + float(shock[0])
        self.tp = self.tp * decay + float(shock[1])

    def close(self, day: date) -> None:
        self.history = [*self.history[-399:], CurveClose(day, dict(self.points))]

    def check(self) -> None:
        """Asserted on every tick; a failure is a bug, not a market event."""
        if not all(math.isfinite(v) and -0.05 < v < 0.5 for v in self.points.values()):
            raise AssertionError(f"G-sec points out of range: {self.points}")
        if not math.isfinite(self.fit.rmse_bp) or self.fit.rmse_bp > 25:
            raise AssertionError(f"NSS refit lost the G-sec points ({self.fit.rmse_bp:.1f} bp)")

    def tick(self, stale: str | None) -> dict[str, Any]:
        return {
            "points": dict(self.points),
            "nss": nss_params(self.fit.curve),
            "rmse_bp": self.fit.rmse_bp,
            "repo_shift": self.repo_shift,
            "as_of": self.anchors.as_of.isoformat(),
            "stale": stale,
        }

    def panel(self) -> dict[str, Any]:
        """The GSEC panel: FBIL's close, the event study, the fitted pass-through and its parts."""
        a = self.anchors
        pt = a.passthrough
        curve = pt.curve
        study = a.study
        grid = PANEL_GRID
        labels = list(FBIL_GSEC_TENORS)
        return {
            "tenors": dict(FBIL_GSEC_TENORS),
            "close": dict(a.close),
            "close_nss": nss_params(a.fit.curve),
            "close_rmse_bp": a.fit.rmse_bp,
            "fbil_par": dict(a.par),
            "as_of": a.as_of.isoformat(),
            "repo_at_close": a.repo,
            "passthrough": {
                "kappa": curve.kappa,
                "gamma": curve.gamma,
                "scale": curve.scale,
                "half_life_years": pt.half_life_years,
                "kappa_band": list(pt.kappa_band),
                "gamma_band": list(pt.gamma_band),
                "beta_10y_band": list(pt.beta_10y_band),
                "rmse": pt.rmse,
                "level": study.level,
                "events": [
                    {
                        "date": e.day.isoformat(),
                        "before": e.before.isoformat(),
                        "change": e.change,
                        "moves": e.moves,
                    }
                    for e in a.events
                ],
                "estimates": [
                    {
                        "tenor": label,
                        "years": float(study.tenors[i]),
                        "relative": float(study.relative[i]),
                        "low": float(study.relative_low[i]),
                        "high": float(study.relative_high[i]),
                        "day_beta": float(study.day_beta[i]),
                    }
                    for i, label in enumerate(labels)
                ],
                "curve": [
                    {"years": float(y), "beta": float(b), "expectations": float(e), "tp": float(p)}
                    for y, b, e, p in zip(
                        grid,
                        curve.beta(grid),
                        curve.expectations(grid),
                        curve.term_premium(grid),
                        strict=True,
                    )
                ],
            },
            "factors": {
                "level_sd": a.factors.level_sd,
                "tp_sd": a.factors.tp_sd,
                "correlation": a.factors.correlation,
                "days": a.factors.days,
                "residual_bp": a.factors.residual_bp,
                "half_life_days": self.params.factor_half_life_days,
                "level": self.level,
                "tp": self.tp,
            },
            "history": [{"date": c.day.isoformat(), "par": c.par} for c in self.history[-120:]],
        }
