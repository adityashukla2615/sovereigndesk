"""Fixed-rate coupon bonds priced on calendar dates.

Two quoting conventions differ only in how the fraction of a period to the next coupon is
discounted (both use simple interest when a single cash flow remains):

* ``"compound"`` — the street (SIA) convention and Excel's PRICE/YIELD, which RBI points
  market participants to for G-secs (basis 4): every flow is discounted by v^(k + w).
* ``"simple"`` — the US Treasury's own formula, 31 CFR Part 356 Appendix B §II.D:
  (P + A)·[1 + (r/s)(i/2)] = C/2 + (C/2)·a_n + 100·vⁿ.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from sovereign_engine._types import FloatArray
from sovereign_engine.bonds.cashflows import (
    CashFlows,
    RiskMeasures,
    _solve_decreasing,
    risk_measures,
)
from sovereign_engine.bonds.daycount import DayCount, coupon_period_fraction
from sovereign_engine.bonds.schedule import CouponPeriod, coupon_period

FractionalPeriod = Literal["compound", "simple"]


@dataclass(frozen=True, slots=True)
class FixedRateBond:
    """A bullet bond paying ``coupon`` (annual rate, decimal) on 100 face, ``freq`` times a year."""

    maturity: date
    coupon: float
    freq: int = 2
    day_count: DayCount = DayCount.ACT_ACT_ICMA
    end_of_month: bool | None = None
    """End-of-month coupon rule; ``None`` applies it exactly when maturity is a month end."""
    redemption: float = 100.0

    def __post_init__(self) -> None:
        if self.coupon < 0 or self.redemption <= 0:
            raise ValueError("coupon must be ≥ 0 and redemption > 0")
        if self.freq not in (1, 2, 3, 4, 6, 12):
            raise ValueError(f"coupon frequency must divide 12, got {self.freq}")


@dataclass(frozen=True, slots=True)
class AccrualState:
    """The bond as seen from one settlement date."""

    period: CouponPeriod
    accrued_fraction: float
    """a = share of the current coupon period already elapsed (A/E)."""
    flows: FloatArray
    """Amount due on each remaining coupon date (coupon, plus redemption at maturity)."""

    @property
    def remaining_fraction(self) -> float:
        """w = 1 − a, the fraction of a period left until the next coupon (DSC/E)."""
        return 1.0 - self.accrued_fraction


def accrual_state(bond: FixedRateBond, settlement: date) -> AccrualState:
    """Coupon period, accrual fraction and remaining flows at ``settlement``.

    Equation:
        a = φ(T_prev, settlement) on the period [T_prev, T_next] under the bond's day count
        CF_k = 100·c/f on each remaining coupon date;  CF_{n−1} += R
    """
    period = coupon_period(bond.maturity, bond.freq, settlement, end_of_month=bond.end_of_month)
    a = coupon_period_fraction(
        period.previous, period.next, period.previous, settlement, bond.day_count, bond.freq
    )
    if a >= 1:
        raise ValueError(f"accrual fraction {a:.4f} reaches a full period under {bond.day_count}")
    flows = np.full(len(period.remaining), 100 * bond.coupon / bond.freq)
    flows[-1] += bond.redemption
    return AccrualState(period=period, accrued_fraction=a, flows=flows)


def accrued_interest(bond: FixedRateBond, settlement: date) -> float:
    """Interest accrued since the last coupon, per 100 face.

    Equation:
        AI = (100·c / f) · a
    """
    return 100 * bond.coupon / bond.freq * accrual_state(bond, settlement).accrued_fraction


def _dirty(state: AccrualState, freq: int, y: float, fractional: FractionalPeriod) -> float:
    if 1 + y / freq <= 0:
        raise ValueError(f"yield {y} is outside the domain 1 + y/f > 0")
    w, flows = state.remaining_fraction, state.flows
    if flows.size == 1:
        return float(flows[0] / (1 + w * y / freq))
    k = np.arange(flows.size, dtype=np.float64)
    log_v = -math.log1p(y / freq)
    if fractional == "compound":
        return float(flows @ np.exp((k + w) * log_v))
    return float(flows @ np.exp(k * log_v) / (1 + w * y / freq))


def dirty_price(
    bond: FixedRateBond, settlement: date, ytm: float, *, fractional: FractionalPeriod = "compound"
) -> float:
    """Full (invoice) price per 100 face at a yield compounded ``freq`` times a year.

    Equation:
        v = 1/(1 + y/f),  w = 1 − a,  n = number of remaining flows
        compound (street):            P_d = Σ_{k=0}^{n−1} CF_k · v^(k + w)
        simple (31 CFR 356 App. B):   P_d = Σ_{k=0}^{n−1} CF_k · v^k / (1 + w·y/f)
        one flow left (both):         P_d = CF_0 / (1 + w·y/f)
    """
    return _dirty(accrual_state(bond, settlement), bond.freq, ytm, fractional)


def clean_price(
    bond: FixedRateBond, settlement: date, ytm: float, *, fractional: FractionalPeriod = "compound"
) -> float:
    """Quoted price per 100 face: the dirty price less accrued interest.

    Equation:
        P_clean = P_dirty − AI
    """
    state = accrual_state(bond, settlement)
    accrued = 100 * bond.coupon / bond.freq * state.accrued_fraction
    return _dirty(state, bond.freq, ytm, fractional) - accrued


def treasury_award_price(bond: FixedRateBond, issue_date: date, high_yield: float) -> float:
    """Auction award price per 100 exactly as Treasury publishes it (31 CFR 356 App. B).

    Accrued interest is rounded to five decimals per $1,000 (§I) before it is subtracted, and
    the price is published to six decimals.

    Equation:
        A = round((s − r)/s · C/2, 6)          per 100 face  (= 5 decimals per $1,000)
        P = round([C/2 + (C/2)·a_n + 100·vⁿ] / [1 + (r/s)(i/2)] − A, 6)        §II.D
    """
    state = accrual_state(bond, issue_date)
    accrued = round(100 * bond.coupon / bond.freq * state.accrued_fraction, 6)
    return round(_dirty(state, bond.freq, high_yield, "simple") - accrued, 6)


def bond_yield(
    bond: FixedRateBond,
    settlement: date,
    clean: float,
    *,
    fractional: FractionalPeriod = "compound",
) -> float:
    """Yield to maturity implied by a clean price.

    Equation:
        solve P_clean(y) = P* for y; P_clean is strictly decreasing in y (bracketing + Brent)
    """
    state = accrual_state(bond, settlement)
    accrued = 100 * bond.coupon / bond.freq * state.accrued_fraction
    floor = -bond.freq * (1 - 1e-9)
    return _solve_decreasing(
        lambda y: _dirty(state, bond.freq, y, fractional), clean + accrued, floor
    )


def bond_cash_flows(bond: FixedRateBond, settlement: date) -> CashFlows:
    """Remaining flows on a time axis consistent with the compound (street) convention.

    Equation:
        t_k = (w + k) / f years,   amounts CF_k,   so that DF(t_k) = v^(k + w)
    """
    state = accrual_state(bond, settlement)
    k = np.arange(state.flows.size, dtype=np.float64)
    return CashFlows(times=(state.remaining_fraction + k) / bond.freq, amounts=state.flows)


def bond_risk(bond: FixedRateBond, settlement: date, ytm: float) -> RiskMeasures:
    """Analytic duration, convexity and DV01 under the compound convention (on the dirty price).

    Equation:
        apply :func:`~sovereign_engine.bonds.cashflows.risk_measures` to t_k = (w + k)/f, m = f
    """
    return risk_measures(bond_cash_flows(bond, settlement), ytm, bond.freq)


def effective_risk(
    bond: FixedRateBond,
    settlement: date,
    ytm: float,
    *,
    fractional: FractionalPeriod = "compound",
    bump: float = 1e-4,
) -> tuple[float, float]:
    """Finite-difference (effective) duration and convexity under either convention.

    Equation:
        D_eff = (P(y − h) − P(y + h)) / (2h · P(y))
        C_eff = (P(y + h) + P(y − h) − 2·P(y)) / (h² · P(y))      (dirty prices)
    """
    state = accrual_state(bond, settlement)
    up, mid, down = (_dirty(state, bond.freq, ytm + s, fractional) for s in (bump, 0.0, -bump))
    return (down - up) / (2 * bump * mid), (up + down - 2 * mid) / (bump * bump * mid)
