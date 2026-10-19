"""Per-market quoting conventions, each with the source it was verified against.

Policy rates are never hardcoded in this project, but market *conventions* are stable
definitions; they live here with a citation and the date they were checked. The tests in
``tests/test_bonds_anchors.py`` reproduce published prices and yields with them.
"""

from dataclasses import dataclass
from datetime import date

from sovereign_engine.bonds.daycount import DayCount
from sovereign_engine.bonds.fixed_rate import FractionalPeriod


@dataclass(frozen=True, slots=True)
class MarketConvention:
    market: str
    instrument: str
    day_count: DayCount
    coupon_frequency: int | None
    """Coupons per year; ``None`` for discount instruments."""
    fractional_period: FractionalPeriod | None
    """How the fraction of a period to the next coupon is discounted (coupon bonds only)."""
    end_of_month: bool | None
    """End-of-month coupon rule; ``None`` means: applied when maturity is a month end."""
    settlement: str
    yield_basis: str
    sources: tuple[str, ...]
    verified: date


_APP_B = "https://www.law.cornell.edu/cfr/text/31/appendix-B_to_part_356"
_RBI_PRIMER = "https://rbi.org.in/scripts/FS_FAQs.aspx?Id=79"
_EXCEL_PRICE = (
    "https://support.microsoft.com/en-us/office/price-function-3ea9deac-8dfa-436f-a7c8-17ea02c21b0a"
)
_VERIFIED = date(2026, 10, 19)

US_TREASURY_COUPON = MarketConvention(
    market="US",
    instrument="Treasury notes and bonds",
    day_count=DayCount.ACT_ACT_ICMA,
    coupon_frequency=2,
    fractional_period="compound",
    end_of_month=None,
    settlement="T+1 (secondary-market practice; not specified by App. B)",
    yield_basis="semiannual bond-equivalent; street convention discounts the first fraction "
    "compounded (Treasury's own App. B formula, used at auction, discounts it simply)",
    sources=(_APP_B, _EXCEL_PRICE),
    verified=_VERIFIED,
)

US_TREASURY_AUCTION = MarketConvention(
    market="US",
    instrument="Treasury notes and bonds, auction award prices",
    day_count=DayCount.ACT_ACT_ICMA,
    coupon_frequency=2,
    fractional_period="simple",
    end_of_month=None,
    settlement="issue date",
    yield_basis="31 CFR 356 App. B §II.D: (P + A)[1 + (r/s)(i/2)] = C/2 + (C/2)a_n + 100v^n",
    sources=(_APP_B,),
    verified=_VERIFIED,
)

US_TREASURY_BILL = MarketConvention(
    market="US",
    instrument="Treasury bills",
    day_count=DayCount.ACT_360,
    coupon_frequency=None,
    fractional_period=None,
    end_of_month=None,
    settlement="T+1 (secondary-market practice; not specified by App. B)",
    yield_basis="bank discount on ACT/360; investment rate on 365 (366 if the year after issue "
    "contains 29 Feb), quadratic beyond half a year (App. B §VI)",
    sources=(_APP_B,),
    verified=_VERIFIED,
)

INDIA_GSEC = MarketConvention(
    market="IN",
    instrument="Government of India dated securities",
    day_count=DayCount.THIRTY_E_360,
    coupon_frequency=2,
    fractional_period="compound",
    end_of_month=False,
    settlement="T+1",
    yield_basis="semiannual; RBI primer Q25: 30/360, Excel YIELD with frequency 2 and basis 4 "
    "(European 30/360)",
    sources=(_RBI_PRIMER, _EXCEL_PRICE),
    verified=_VERIFIED,
)

INDIA_TBILL = MarketConvention(
    market="IN",
    instrument="Treasury bills (91/182/364-day)",
    day_count=DayCount.ACT_365F,
    coupon_frequency=None,
    fractional_period=None,
    end_of_month=None,
    settlement="T+1",
    yield_basis="implicit yield y = (100 − P)/P × 365/D (RBI primer Q25-26; RBI auction releases)",
    sources=(_RBI_PRIMER, "https://rbi.org.in/ScriptS/BS_PressReleaseDisplay.aspx?prid=63210"),
    verified=_VERIFIED,
)

ALL_CONVENTIONS = (
    US_TREASURY_COUPON,
    US_TREASURY_AUCTION,
    US_TREASURY_BILL,
    INDIA_GSEC,
    INDIA_TBILL,
)
