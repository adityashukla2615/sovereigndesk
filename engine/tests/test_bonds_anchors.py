"""Reproduce officially published prices, yields and accrued interest.

Fixtures come from ``scripts/fetch_engine_fixtures.py`` (TreasuryDirect auction results); the
RBI and 31 CFR examples are quoted from the documents cited in ``bonds/conventions.py``.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from sovereign_engine.bonds.bills import (
    india_tbill_price,
    india_tbill_yield,
    us_bill_discount_rate,
    us_bill_investment_rate,
    us_bill_price,
    us_bill_year_basis,
)
from sovereign_engine.bonds.conventions import ALL_CONVENTIONS, INDIA_GSEC
from sovereign_engine.bonds.daycount import DayCount
from sovereign_engine.bonds.fixed_rate import (
    FixedRateBond,
    accrual_state,
    accrued_interest,
    bond_risk,
    bond_yield,
    clean_price,
    dirty_price,
    effective_risk,
    treasury_award_price,
)

FIXTURES = Path(__file__).parent / "fixtures"
AUCTIONS: dict[str, Any] = json.loads(
    (FIXTURES / "treasurydirect_auctions.json").read_text("utf-8")
)


def _d(value: str) -> date:
    return date.fromisoformat(value[:10])


@pytest.mark.parametrize("row", AUCTIONS["coupons"], ids=lambda r: f"{r['cusip']}-{r['issueDate']}")
def test_treasury_auction_price_and_accrued(row: dict[str, str]) -> None:
    """31 CFR 356 App. B §I/§II.D reproduces every published award price and accrued interest."""
    bond = FixedRateBond(maturity=_d(row["maturityDate"]), coupon=float(row["interestRate"]) / 100)
    issue = _d(row["issueDate"])
    assert accrual_state(bond, issue).period.previous == _d(row["datedDate"])

    accrued_per_1000 = round(10 * accrued_interest(bond, issue), 5)
    assert accrued_per_1000 == pytest.approx(float(row["accruedInterest"] or 0), abs=1e-9)

    high_yield = float(row["highYield"]) / 100
    assert treasury_award_price(bond, issue, high_yield) == float(row["highPrice"])
    # Before Treasury's rounding of accrued interest the formula is within a micro-point.
    unrounded = clean_price(bond, issue, high_yield, fractional="simple")
    assert unrounded == pytest.approx(float(row["highPrice"]), abs=1e-6)


def test_appendix_b_worked_example() -> None:
    """App. B §II.D example: 9½% note due 15 Nov 1995, accruing from 15 Nov 1985, issued
    29 Nov 1985 at 9.54%: n = 19, r = 167, s = 181, A = .367403, P = 99.730918."""
    bond = FixedRateBond(maturity=date(1995, 11, 15), coupon=0.095)
    issue = date(1985, 11, 29)
    state = accrual_state(bond, issue)
    assert len(state.flows) - 1 == 19
    assert (state.period.next - issue).days == 167
    assert (state.period.next - state.period.previous).days == 181
    assert accrued_interest(bond, issue) == pytest.approx(0.367403, abs=5e-7)
    assert treasury_award_price(bond, issue, 0.0954) == 99.730918


@pytest.mark.parametrize("row", AUCTIONS["bills"], ids=lambda r: f"{r['cusip']}-{r['issueDate']}")
def test_treasury_bill_auctions(row: dict[str, str]) -> None:
    days = int(row["daysIssueToMaturity"])
    assert days == (_d(row["maturityDate"]) - _d(row["issueDate"])).days
    award = float(row["highPrice"])
    assert us_bill_price(float(row["highRate"]) / 100, days) == pytest.approx(award, abs=5e-7)
    # The award price is rounded to 6 decimals, which bounds how well the rate can be recovered.
    rate_tol = 0.5e-6 / 100 * 360 / days
    assert us_bill_discount_rate(award, days) == pytest.approx(
        float(row["highRate"]) / 100, abs=rate_tol
    )
    basis = us_bill_year_basis(_d(row["issueDate"]))
    investment = us_bill_investment_rate(award, days, basis)
    assert round(investment * 100, 3) == pytest.approx(float(row["investmentRate"]), abs=1e-9)


def test_leap_year_basis_is_required() -> None:
    # 4-week bill issued 14 Nov 2023: the year ahead contains 29 Feb 2024, so y = 366.
    assert us_bill_year_basis(date(2023, 11, 14)) == 366
    assert us_bill_year_basis(date(2026, 10, 8)) == 365
    assert round(100 * us_bill_investment_rate(99.588556, 28, 366), 3) == 5.400
    assert round(100 * us_bill_investment_rate(99.588556, 28, 365), 3) != 5.400


@pytest.mark.parametrize(
    ("days", "cutoff_price", "implicit_yield"),
    [(91, 98.6827, 5.3542), (182, 97.2789, 5.6098), (364, 94.5634, 5.7650)],
)
def test_rbi_tbill_auction(days: int, cutoff_price: float, implicit_yield: float) -> None:
    """RBI press release 2026-2027/732 (22 Jul 2026): cut-off prices and implicit yields."""
    assert 100 * india_tbill_yield(cutoff_price, days) == pytest.approx(implicit_yield, abs=5e-5)
    assert india_tbill_price(implicit_yield / 100, days) == pytest.approx(cutoff_price, abs=1e-4)


def test_rbi_gsec_accrued_interest() -> None:
    """RBI primer: 8.83% GS 2023 settled 30 Jan 2014 accrues 65 days: 8.83 × 65/360 = 1.5943."""
    bond = FixedRateBond(
        maturity=date(2023, 11, 25),
        coupon=0.0883,
        day_count=DayCount.THIRTY_E_360,
        end_of_month=False,
    )
    assert accrued_interest(bond, date(2014, 1, 30)) == pytest.approx(1.5943, abs=5e-5)
    assert INDIA_GSEC.day_count is DayCount.THIRTY_E_360


def test_conventions_cite_sources() -> None:
    for convention in ALL_CONVENTIONS:
        assert convention.sources
        assert all(url.startswith("https://") for url in convention.sources)
        assert convention.verified >= date(2026, 10, 19)


SETTLE = date(2026, 10, 20)
TEN_YEAR = FixedRateBond(maturity=date(2036, 8, 15), coupon=0.04625)


@pytest.mark.parametrize("fractional", ["compound", "simple"])
def test_bond_yield_round_trip(fractional: str) -> None:
    for ytm in (0.001, 0.0468, 0.12):
        clean = clean_price(TEN_YEAR, SETTLE, ytm, fractional=fractional)  # type: ignore[arg-type]
        solved = bond_yield(TEN_YEAR, SETTLE, clean, fractional=fractional)  # type: ignore[arg-type]
        assert solved == pytest.approx(ytm, abs=1e-12)


def test_conventions_differ_only_in_the_fractional_period() -> None:
    y, f = 0.05, 2
    w = accrual_state(TEN_YEAR, SETTLE).remaining_fraction
    street = dirty_price(TEN_YEAR, SETTLE, y)
    treasury = dirty_price(TEN_YEAR, SETTLE, y, fractional="simple")
    assert street / treasury == pytest.approx((1 + w * y / f) * (1 + y / f) ** -w, rel=1e-14)
    on_coupon = date(2027, 2, 15)
    assert clean_price(TEN_YEAR, on_coupon, 0.05) == pytest.approx(
        clean_price(TEN_YEAR, on_coupon, 0.05, fractional="simple"), abs=1e-12
    )


def test_final_period_uses_simple_interest() -> None:
    bond = FixedRateBond(maturity=date(2027, 2, 15), coupon=0.04)
    settle = date(2026, 11, 15)
    state = accrual_state(bond, settle)
    expected = 102.0 / (1 + state.remaining_fraction * 0.05 / 2)
    assert dirty_price(bond, settle, 0.05) == pytest.approx(expected, rel=1e-14)
    assert dirty_price(bond, settle, 0.05, fractional="simple") == pytest.approx(
        expected, rel=1e-14
    )


def test_analytic_and_effective_risk_agree() -> None:
    risk = bond_risk(TEN_YEAR, SETTLE, 0.05)
    duration, convex = effective_risk(TEN_YEAR, SETTLE, 0.05)
    assert risk.price == pytest.approx(dirty_price(TEN_YEAR, SETTLE, 0.05), rel=1e-12)
    assert duration == pytest.approx(risk.modified_duration, rel=1e-6)
    assert convex == pytest.approx(risk.convexity, rel=1e-4)
