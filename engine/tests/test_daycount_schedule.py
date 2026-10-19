from datetime import date

import pytest

from sovereign_engine.bonds.daycount import (
    DayCount,
    coupon_period_fraction,
    day_count,
    days_30_360,
    days_30e_360,
    year_fraction,
)
from sovereign_engine.bonds.schedule import add_months, coupon_period, is_month_end


@pytest.mark.parametrize(
    ("start", "end", "bond_basis", "eurobond"),
    [
        (date(2026, 1, 15), date(2026, 7, 15), 180, 180),
        (date(2026, 1, 31), date(2026, 3, 31), 60, 60),
        (date(2026, 1, 30), date(2026, 3, 31), 60, 60),
        (date(2026, 1, 29), date(2026, 3, 31), 62, 61),  # the variants differ when D1 < 30
        (date(2026, 2, 28), date(2026, 3, 31), 33, 32),
        # RBI primer accrued-interest example: 25 Nov 2013 → 30 Jan 2014 is 65 days.
        (date(2013, 11, 25), date(2014, 1, 30), 65, 65),
    ],
)
def test_thirty_360_variants(start: date, end: date, bond_basis: int, eurobond: int) -> None:
    assert days_30_360(start, end) == bond_basis
    assert days_30e_360(start, end) == eurobond
    assert day_count(start, end, DayCount.THIRTY_360) == bond_basis
    assert day_count(start, end, DayCount.THIRTY_E_360) == eurobond


def test_actual_conventions() -> None:
    start, end = date(2026, 8, 15), date(2027, 2, 15)
    assert day_count(start, end, DayCount.ACT_ACT_ICMA) == 184
    assert year_fraction(start, end, DayCount.ACT_360) == pytest.approx(184 / 360)
    assert year_fraction(start, end, DayCount.ACT_365F) == pytest.approx(184 / 365)
    with pytest.raises(ValueError, match="reference coupon period"):
        year_fraction(start, end, DayCount.ACT_ACT_ICMA)


def test_coupon_period_fraction() -> None:
    period = (date(2026, 8, 15), date(2027, 2, 15))
    settle = date(2026, 10, 15)
    icma = coupon_period_fraction(*period, period[0], settle, DayCount.ACT_ACT_ICMA, 2)
    assert icma == pytest.approx(61 / 184)
    e30 = coupon_period_fraction(*period, period[0], settle, DayCount.THIRTY_E_360, 2)
    assert e30 == pytest.approx(60 / 180)
    with pytest.raises(ValueError, match="inside the coupon period"):
        coupon_period_fraction(*period, period[0], date(2027, 3, 1), DayCount.ACT_ACT_ICMA, 2)


@pytest.mark.parametrize(
    ("start", "months", "eom", "expected"),
    [
        (date(2026, 1, 31), 1, False, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, False, date(2028, 2, 29)),
        (date(2026, 2, 28), 6, True, date(2026, 8, 31)),
        (date(2026, 2, 28), 6, False, date(2026, 8, 28)),
        (date(2026, 9, 30), -6, True, date(2026, 3, 31)),
        (date(2026, 9, 30), -6, False, date(2026, 3, 30)),
        (date(2026, 3, 31), -1, False, date(2026, 2, 28)),
        (date(2026, 11, 15), 3, False, date(2027, 2, 15)),
    ],
)
def test_add_months(start: date, months: int, eom: bool, expected: date) -> None:
    assert add_months(start, months, end_of_month=eom) == expected


def test_month_end() -> None:
    assert is_month_end(date(2028, 2, 29))
    assert not is_month_end(date(2026, 2, 27))


def test_us_month_end_schedule_does_not_drift() -> None:
    # A 2-year note dated 31 May pays on 30 Nov and 31 May (TreasuryDirect accrues 1/183).
    period = coupon_period(date(2028, 5, 31), 2, date(2026, 6, 1))
    assert period.previous == date(2026, 5, 31)
    assert period.remaining == (
        date(2026, 11, 30),
        date(2027, 5, 31),
        date(2027, 11, 30),
        date(2028, 5, 31),
    )
    assert (period.next - period.previous).days == 183


def test_fixed_day_schedule_and_coupon_date_settlement() -> None:
    india = coupon_period(date(2028, 1, 8), 2, date(2026, 10, 19), end_of_month=False)
    assert (india.previous, india.remaining) == (
        date(2026, 7, 8),
        (date(2027, 1, 8), date(2027, 7, 8), date(2028, 1, 8)),
    )
    on_coupon = coupon_period(date(2029, 10, 15), 2, date(2026, 10, 15))
    assert on_coupon.previous == date(2026, 10, 15)
    assert len(on_coupon.remaining) == 6


def test_schedule_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="before maturity"):
        coupon_period(date(2026, 1, 1), 2, date(2026, 1, 1))
    with pytest.raises(ValueError, match="divide 12"):
        coupon_period(date(2030, 1, 1), 5, date(2026, 1, 1))
