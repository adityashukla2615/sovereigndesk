"""Price impact of large Treasury sales (e.g. a foreign holder selling), along the curve.

Calibrated by default to Beltran, Kretchmer, Marquez and Thomas (2012, Fed IFDP 1041; JIMF 2013):
a $100bn drop in foreign official inflows within a month raises 5-year yields by about 40–60 bp
in the short run and about 20 bp in the long run, once private investors respond. Here that is
a permanent component (20 bp per $100bn) plus a temporary one (30 bp at a pace of $100bn a
month) that tracks the selling pace and decays with a half-life once selling stops.

Their sample ends in 2010, when the market was far smaller; impact is scaled by
``reference_market / market`` (debt held by the public then vs now). The gilt-crisis replay
(Phase 11) checks the permanent coefficient independently: its fire-sale λ, moved over to
Treasuries by the depth ratio, gives about 7 bp per $100bn sold, against 5 bp here at today's
market size.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array

BUCKET_TENORS: dict[str, float] = {"SHORT": 2.0, "BELLY": 5.0, "LONG": 20.0}
"""Centre maturity (years) of each tenor bucket a sale can target."""


@dataclass(frozen=True, slots=True)
class PriceImpactModel:
    reference_market: float
    """Treasury debt held by the public (USD bn) when the coefficients were estimated."""
    permanent_bp: float = 20.0
    """Long-run yield rise at the bucket centre per ``reference_sale`` sold."""
    temporary_bp: float = 30.0
    """Extra short-run rise at the bucket centre while selling at ``reference_pace``."""
    reference_sale: float = 100.0
    """USD bn."""
    reference_pace: float = 100.0 / (365.25 / 12)
    """USD bn per calendar day: $100bn over one average month (the simulator runs calendar days)."""
    half_life_days: float = 5.0
    """Half-life of the temporary component once the selling pace changes."""
    kernel_years: float = 5.0
    """How far along the curve a bucket's impact reaches."""

    def __post_init__(self) -> None:
        if min(self.reference_market, self.reference_sale, self.reference_pace) <= 0:
            raise ValueError("reference market, sale and pace must be positive")
        if self.half_life_days <= 0 or self.kernel_years <= 0:
            raise ValueError("half-life and kernel width must be positive")

    def kernel(self, tenors: ArrayLike, centre: float) -> FloatArray:
        """How impact at a bucket centre spreads to other maturities.

        Equation:
            w(τ) = e^(−|τ − τ_k| / ℓ)
        """
        return np.exp(-np.abs(as_float_array(tenors) - centre) / self.kernel_years)

    def permanent(self, sold: Mapping[str, float], market: float, tenors: ArrayLike) -> FloatArray:
        """Long-run yield change (decimal) across ``tenors`` from cumulative sales by bucket.

        Equation:
            Δy_perm(τ) = Σ_k κ · (Q_k / Q_ref) · (M_ref / M) · w_k(τ),   κ = permanent_bp
        """
        scale = self.reference_market / market
        total = np.zeros_like(as_float_array(tenors))
        for bucket, amount in sold.items():
            weight = self.kernel(tenors, BUCKET_TENORS[bucket])
            total += self.permanent_bp * 1e-4 * amount / self.reference_sale * scale * weight
        return total

    def temporary_target(
        self, pace: Mapping[str, float], market: float, tenors: ArrayLike
    ) -> FloatArray:
        """Short-run excess yield (decimal) sustained by the current selling pace (square-root law).

        Equation:
            T*(τ) = Σ_k η · √(q_k / q_ref) · (M_ref / M) · w_k(τ),   η = temporary_bp
        """
        scale = self.reference_market / market
        total = np.zeros_like(as_float_array(tenors))
        for bucket, rate in pace.items():
            if rate > 0:
                weight = self.kernel(tenors, BUCKET_TENORS[bucket])
                total += (
                    self.temporary_bp
                    * 1e-4
                    * math.sqrt(rate / self.reference_pace)
                    * scale
                    * weight
                )
        return total

    def relax(self, current: ArrayLike, target: ArrayLike, days: float) -> FloatArray:
        """Move the temporary component toward its target with the configured half-life.

        Equation:
            T(t + Δ) = T* + (T(t) − T*) · 2^(−Δ / h)
        """
        decay = 2 ** (-days / self.half_life_days)
        tgt = as_float_array(target)
        return tgt + (as_float_array(current) - tgt) * decay


def split_sale(amount: float, mix: str | Mapping[str, float]) -> dict[str, float]:
    """Split a sale across buckets: a bucket name, or explicit shares that sum to one.

    Equation:
        Q_k = Q · share_k,   Σ_k share_k = 1
    """
    shares = {mix: 1.0} if isinstance(mix, str) else dict(mix)
    if set(shares) - set(BUCKET_TENORS) or not math.isclose(sum(shares.values()), 1.0):
        raise ValueError(
            f"mix must name buckets from {sorted(BUCKET_TENORS)} with shares summing to 1"
        )
    return {bucket: amount * share for bucket, share in shares.items()}
