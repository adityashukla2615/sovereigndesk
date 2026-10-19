"""Day-count conventions: how many days count between two dates, and as what fraction of a period.

Which market uses which convention is recorded, with sources, in :mod:`.conventions`.
"""

from datetime import date
from enum import StrEnum


class DayCount(StrEnum):
    ACT_ACT_ICMA = "ACT/ACT ICMA"
    """Actual days over actual days in the coupon period (US Treasuries, gilts)."""
    THIRTY_360 = "30/360"
    """30/360 Bond Basis, ISDA 2006 §4.16(f)."""
    THIRTY_E_360 = "30E/360"
    """30E/360 Eurobond Basis, ISDA 2006 §4.16(g); Excel basis 4 (Indian G-secs)."""
    ACT_360 = "ACT/360"
    ACT_365F = "ACT/365F"


def _thirty_360(start: date, end: date, d1: int, d2: int) -> int:
    return 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)


def days_30_360(start: date, end: date) -> int:
    """Day count under 30/360 Bond Basis (ISDA 2006 §4.16(f)).

    Equation:
        N = 360·(Y2 − Y1) + 30·(M2 − M1) + (D2 − D1)
        D1 → 30 if D1 = 31;   D2 → 30 if D2 = 31 and D1 ≥ 30 (after D1's adjustment)
    """
    d1 = min(start.day, 30)
    d2 = 30 if end.day == 31 and d1 >= 30 else end.day
    return _thirty_360(start, end, d1, d2)


def days_30e_360(start: date, end: date) -> int:
    """Day count under 30E/360 Eurobond Basis (ISDA 2006 §4.16(g)).

    Equation:
        N = 360·(Y2 − Y1) + 30·(M2 − M1) + (D2 − D1)
        D1 → 30 if D1 = 31;   D2 → 30 if D2 = 31
    """
    return _thirty_360(start, end, min(start.day, 30), min(end.day, 30))


def day_count(start: date, end: date, convention: DayCount) -> int:
    """Days counted between two dates.

    Equation:
        ACT conventions: N = end − start (calendar days)
        30/360, 30E/360: N as in :func:`days_30_360` / :func:`days_30e_360`
    """
    match convention:
        case DayCount.THIRTY_360:
            return days_30_360(start, end)
        case DayCount.THIRTY_E_360:
            return days_30e_360(start, end)
        case _:
            return (end - start).days


def year_fraction(start: date, end: date, convention: DayCount) -> float:
    """Year fraction for conventions with a fixed denominator.

    ACT/ACT ICMA has no fixed denominator (it depends on the coupon period), so use
    :func:`coupon_period_fraction` for it.

    Equation:
        τ = N / 360 for ACT/360, 30/360, 30E/360;   τ = N / 365 for ACT/365F
    """
    if convention is DayCount.ACT_ACT_ICMA:
        raise ValueError("ACT/ACT ICMA needs a reference coupon period; use coupon_period_fraction")
    basis = 365 if convention is DayCount.ACT_365F else 360
    return day_count(start, end, convention) / basis


def coupon_period_fraction(
    period_start: date, period_end: date, start: date, end: date, convention: DayCount, freq: int
) -> float:
    """Fraction of the coupon period [period_start, period_end] covered by [start, end].

    Equation:
        ACT/ACT ICMA:    φ = (end − start) / (period_end − period_start)    in actual days
        30/360, 30E/360: φ = N_30(start, end) / (360 / f)
        ACT/360:         φ = (end − start) / (360 / f)
        ACT/365F:        φ = (end − start) / (365 / f)
    """
    if not period_start <= start <= end <= period_end:
        raise ValueError("[start, end] must lie inside the coupon period")
    if convention is DayCount.ACT_ACT_ICMA:
        return (end - start).days / (period_end - period_start).days
    basis = 365 if convention is DayCount.ACT_365F else 360
    return day_count(start, end, convention) / (basis / freq)
