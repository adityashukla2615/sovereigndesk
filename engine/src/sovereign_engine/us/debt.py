"""Federal debt service: roll the marketable maturity ladder over at a yield path.

Each month, maturing securities are refinanced like-for-like (same original term, at that
month's yield for the term) and the month's deficit is financed with an issuance mix. The
default mix is the steady-state gross issuance implied by the debt stock, shares ∝ stock/term,
which is what like-for-like rollover of today's composition generates. Interest is the
annualised coupon, or bill yield, on everything outstanding.

TIPS earn their real coupon plus an inflation assumption and are reissued as nominal debt; FRNs
pay the 3-month yield plus a spread. Both are approximations. Amounts are USD billions, rates
decimals.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from sovereign_engine._types import FloatArray

Kind = Literal["bill", "note", "bond", "tips", "frn"]


@dataclass(frozen=True, slots=True)
class DebtSecurity:
    kind: Kind
    maturity: date
    rate: float
    """Coupon rate (notes, bonds; TIPS real coupon) or yield at issue (bills); FRN: ignored."""
    outstanding: float
    term: float
    """Years to maturity at original issue (the term it is rolled into when it matures)."""


@dataclass(frozen=True, slots=True)
class IssuanceMix:
    tenors: tuple[float, ...]
    """Years to maturity at issue."""
    shares: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.tenors) != len(self.shares) or not self.tenors:
            raise ValueError("tenors and shares must be non-empty and the same length")
        if min(self.tenors) <= 0 or min(self.shares) < 0 or not np.isclose(sum(self.shares), 1):
            raise ValueError("tenors must be positive and shares non-negative, summing to 1")

    @classmethod
    def from_stock(cls, stock_by_term: Mapping[float, float]) -> "IssuanceMix":
        """Gross issuance mix that keeps the stock's composition in steady state.

        A term-T security is reissued every T years, so it accounts for stock/T of yearly
        gross issuance.

        Equation:
            share_T = (S_T / T) / Σ_τ (S_τ / τ)
        """
        flows = {
            term: stock / term for term, stock in stock_by_term.items() if stock > 0 and term > 0
        }
        if not flows:
            raise ValueError("need a positive stock at a positive term")
        total = sum(flows.values())
        tenors = tuple(sorted(flows))
        return cls(tenors=tenors, shares=tuple(flows[t] / total for t in tenors))


@dataclass(frozen=True, slots=True)
class DebtPath:
    months: list[date]
    outstanding: FloatArray
    interest: FloatArray
    """Annualised interest cost in each month (USD bn per year)."""
    average_rate: FloatArray
    interest_to_gdp: FloatArray
    interest_to_receipts: FloatArray


def _month_index(start: date, when: date) -> int:
    return (when.year - start.year) * 12 + (when.month - start.month)


def _add_months(start: date, months: int) -> date:
    index = start.year * 12 + start.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


YieldPath = Callable[[int, float], float]
"""yield_at(month_index, tenor_years) → yield (decimal)."""


@dataclass(slots=True)
class _Holding:
    due: int
    kind: Kind
    rate: float
    amount: float
    term: float


def project_debt_service(
    ladder: Sequence[DebtSecurity],
    *,
    start: date,
    months: int,
    yield_at: YieldPath,
    mix: IssuanceMix,
    monthly_deficit: float,
    nominal_gdp: float,
    annual_receipts: float,
    nominal_growth: float = 0.04,
    inflation: float = 0.025,
    frn_spread: float = 0.001,
) -> DebtPath:
    """Monthly projection of marketable debt outstanding and its annualised interest cost.

    Equation:
        maturing term-T debt is reissued at y_m(T);  deficit_m · share_j is issued at y_m(τ_j)
        I_m = Σᵢ Oᵢ · rᵢ   (TIPS: r_real + π;  FRN: y_m(0.25) + spread)
        GDP_m = GDP₀·(1 + g)^(m/12),   receipts_m = receipts₀·(1 + g)^(m/12)
    """
    if months < 1:
        raise ValueError("need at least one month")
    first = date(start.year, start.month, 1)
    book = [
        _Holding(max(_month_index(first, s.maturity), 0), s.kind, s.rate, s.outstanding, s.term)
        for s in ladder
        if s.outstanding > 0 and s.maturity >= first
    ]
    out = np.empty(months)
    interest = np.empty(months)
    dates = []
    for m in range(months):
        rolling: dict[tuple[float, Kind], float] = defaultdict(float)
        kept = []
        for h in book:
            if h.due == m:
                rolling[(h.term, "frn" if h.kind == "frn" else "note")] += h.amount
            else:
                kept.append(h)
        book = kept
        for tenor, share in zip(mix.tenors, mix.shares, strict=True):
            if monthly_deficit * share > 0:
                rolling[(tenor, "note")] += monthly_deficit * share
        for (term, kind), amount in rolling.items():
            due = m + max(round(term * 12), 1)
            book.append(_Holding(due, kind, yield_at(m, term), amount, term))
        three_month = yield_at(m, 0.25)
        total = cost = 0.0
        for h in book:
            total += h.amount
            if h.kind == "tips":
                cost += h.amount * (h.rate + inflation)
            elif h.kind == "frn":
                cost += h.amount * (three_month + frn_spread)
            else:
                cost += h.amount * h.rate
        out[m], interest[m] = total, cost
        dates.append(_add_months(first, m))
    growth = (1 + nominal_growth) ** (np.arange(months) / 12)
    return DebtPath(
        months=dates,
        outstanding=out,
        interest=interest,
        average_rate=interest / np.where(out > 0, out, 1.0),
        interest_to_gdp=interest / (nominal_gdp * growth),
        interest_to_receipts=interest / (annual_receipts * growth),
    )
