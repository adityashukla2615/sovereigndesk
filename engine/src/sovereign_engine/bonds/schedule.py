"""Regular coupon schedules, rolled back from maturity.

Dates are unadjusted: when a coupon date is a holiday the payment moves to the next business
day, but accrual still runs between the unadjusted dates (US Treasury and RBI practice alike).
Odd (short or long) first coupons are out of scope; secondary-market pricing only needs the
regular periods after the first coupon.
"""

import calendar
from dataclasses import dataclass
from datetime import date


def month_length(year: int, month: int) -> int:
    """Number of days in a calendar month.

    Equation:
        L(Y, M) ∈ {28, 29, 30, 31} per the Gregorian calendar (29 for February in leap years)
    """
    return calendar.monthrange(year, month)[1]


def is_month_end(d: date) -> bool:
    """True when ``d`` is the last day of its month.

    Equation:
        d is a month end ⇔ D = L(Y, M)
    """
    return d.day == month_length(d.year, d.month)


def add_months(d: date, months: int, *, end_of_month: bool = False) -> date:
    """Shift a date by whole months, clipping to the month's length.

    Equation:
        (Y', M') = (Y, M) + n months
        D' = L(Y', M')            if end_of_month and D = L(Y, M)
        D' = min(D, L(Y', M'))    otherwise
    """
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = month_length(year, month)
    day = last if end_of_month and is_month_end(d) else min(d.day, last)
    return date(year, month, day)


@dataclass(frozen=True, slots=True)
class CouponPeriod:
    """Where a settlement date sits in a bond's regular coupon schedule."""

    previous: date
    """Last coupon date on or before settlement: the start of the current accrual period."""
    remaining: tuple[date, ...]
    """Every coupon date after settlement, ascending; the last one is the maturity date."""

    @property
    def next(self) -> date:
        return self.remaining[0]


def coupon_period(
    maturity: date, freq: int, settlement: date, *, end_of_month: bool | None = None
) -> CouponPeriod:
    """Locate ``settlement`` in the regular schedule rolled back from ``maturity``.

    Each date is computed from maturity directly, never from its neighbour, so month-end
    clipping cannot drift (31 Aug → 28 Feb → 28 Aug would be wrong). ``end_of_month=None``
    applies the end-of-month rule exactly when maturity is a month end, which is how US
    Treasuries maturing on the last day of a month pay (e.g. 31 Mar / 30 Sep).

    Equation:
        T_k = add_months(maturity, −k·12/f),   k = 0, 1, 2, …
        previous = max{T_k : T_k ≤ settlement},   remaining = {T_k : T_k > settlement}
    """
    if freq not in (1, 2, 3, 4, 6, 12):
        raise ValueError(f"coupon frequency must divide 12, got {freq}")
    if settlement >= maturity:
        raise ValueError("settlement must be before maturity")
    eom = is_month_end(maturity) if end_of_month is None else end_of_month
    step = 12 // freq
    after: list[date] = []
    k = 0
    while (coupon := add_months(maturity, -k * step, end_of_month=eom)) > settlement:
        after.append(coupon)
        k += 1
    return CouponPeriod(previous=coupon, remaining=tuple(reversed(after)))
