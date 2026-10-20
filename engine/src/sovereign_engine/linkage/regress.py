"""Least squares with Newey–West standard errors, for the linkage's calibration.

The linkage's coefficients come from monthly and weekly time series whose errors are
autocorrelated and heteroskedastic (flows bunch in episodes), so the standard errors are
Newey–West (Bartlett kernel) rather than the classical ones.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array

Z90 = 1.6448536269514722
"""The standard normal's 95th percentile: a 90% two-sided interval."""


@dataclass(frozen=True, slots=True)
class OlsFit:
    names: tuple[str, ...]
    """Regressor names; "const" first when the fit has a constant."""
    coef: FloatArray
    se: FloatArray
    """Newey–West standard errors."""
    r2: float
    n: int
    lags: int

    def value(self, name: str) -> float:
        """One coefficient.

        Equation:
            β̂_k for the regressor named k
        """
        return float(self.coef[self.names.index(name)])

    def interval(self, name: str, z: float = Z90) -> tuple[float, float]:
        """A normal-approximation interval for one coefficient (90% by default).

        Equation:
            β̂_k ± z · se(β̂_k)
        """
        k = self.names.index(name)
        return float(self.coef[k] - z * self.se[k]), float(self.coef[k] + z * self.se[k])


def ols_hac(
    y: ArrayLike, regressors: Mapping[str, ArrayLike], *, lags: int, constant: bool = True
) -> OlsFit:
    """Ordinary least squares with Newey–West (HAC) standard errors. Rows with a missing value
    in ``y`` or any regressor are dropped.

    Equation:
        β̂ = (XᵀX)⁻¹ Xᵀy,   V̂ = (XᵀX)⁻¹ Ŝ (XᵀX)⁻¹,
        Ŝ = Σₜ ûₜ² xₜxₜᵀ + Σ_{l=1}^{L} (1 − l/(L+1)) Σₜ ûₜûₜ₋ₗ (xₜxₜ₋ₗᵀ + xₜ₋ₗxₜᵀ),
        R² = 1 − Σûₜ² / Σ(yₜ − ȳ)²
    """
    target = as_float_array(y)
    names = (("const",) if constant else ()) + tuple(regressors)
    columns = [np.ones_like(target)] if constant else []
    columns += [as_float_array(v) for v in regressors.values()]
    x = np.column_stack(columns)
    keep = np.isfinite(target) & np.all(np.isfinite(x), axis=1)
    x, target = x[keep], target[keep]
    n, k = x.shape
    if n <= k:
        raise ValueError(f"{n} observations cannot identify {k} coefficients")
    xtx_inv = np.linalg.inv(x.T @ x)
    coef = xtx_inv @ x.T @ target
    resid = target - x @ coef
    scores = x * resid[:, None]
    s = scores.T @ scores
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (lags + 1)
        gamma = scores[lag:].T @ scores[:-lag]
        s += weight * (gamma + gamma.T)
    cov = xtx_inv @ s @ xtx_inv
    centred = target - target.mean()
    tss = float(centred @ centred)
    r2 = 1.0 - float(resid @ resid) / tss if tss > 0 else 0.0
    return OlsFit(names, coef, np.sqrt(np.clip(np.diag(cov), 0.0, None)), r2, n, lags)
