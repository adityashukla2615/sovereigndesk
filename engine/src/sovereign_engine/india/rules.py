"""RBI rules the bank universe obeys, each tied to the document it was checked against.

Rates that change with policy (CRR, SLR, repo, SDF, MSF) are *not* defaults here: the simulator
reads them from RBI's published data. What lives here are rule parameters, each with a source.
The one exception is the lending limit: RBI's directions set no lending cap, so participants
use board-approved internal limits; the values here are an assumption and labelled as one.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Citation:
    rule: str
    document: str
    url: str
    verified: date


_VERIFIED = date(2026, 10, 20)

CITATIONS: tuple[Citation, ...] = (
    Citation(
        "Call/notice money borrowing: SCBs 100% of capital funds (fortnightly daily average) and "
        "125% on any day; primary dealers 225% of net owned funds; term money within "
        "board-approved limits. No lending limits are prescribed.",
        "RBI/2021-22/61, FMRD.DIRD.06/14.01.001/2021-22 (25 Jun 2021), Call, Notice and Term "
        "Money Markets Directions, Table 1",
        "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12120",
        _VERIFIED,
    ),
    Citation(
        "CRR: maintain the fortnightly average; the daily minimum rose from 90% to 99% of the "
        "requirement from the fortnight beginning 16 Oct 2026 (all scheduled banks).",
        "RBI/2026-27/290, DoR.RET.REC.247/12.01.001/2026-27 (9 Oct 2026)",
        "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=13736",
        _VERIFIED,
    ),
    Citation(
        "MSF: banks may dip into SLR up to 2% of NDTL for overnight MSF borrowing (restored from "
        "3% with effect from 1 Jan 2022).",
        "RBI/2021-22/138 (10 Dec 2021)",
        "https://rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx?Id=12207",
        _VERIFIED,
    ),
)


@dataclass(frozen=True, slots=True)
class MoneyMarketRules:
    crr: float
    """Cash reserve ratio, fraction of NDTL (from RBI data)."""
    slr: float
    """Statutory liquidity ratio, fraction of NDTL (from RBI data)."""
    # VERIFY: RBI/2026-27/290, from the fortnight beginning 16 Oct 2026 (checked 2026-10-20)
    crr_daily_min_share: float = 0.99
    # VERIFY: RBI/2021-22/138, from 1 Jan 2022 (checked 2026-10-20)
    msf_slr_dip: float = 0.02
    # VERIFY: RBI/2021-22/61, Table 1, for this and the next two (checked 2026-10-20)
    bank_borrow_avg: float = 1.00
    """× capital funds, fortnightly daily average (call + notice)."""
    bank_borrow_peak: float = 1.25
    """× capital funds, any single day."""
    pd_borrow_avg: float = 2.25
    """× net owned funds, fortnightly daily average; RBI states no daily maximum for PDs."""
    lend_avg: float = 0.25
    """ASSUMPTION: board-approved internal lending limit, × capital funds (RBI sets none)."""
    lend_peak: float = 0.50
    """ASSUMPTION: board-approved internal daily lending limit, × capital funds."""
    fortnight_days: int = 14

    def __post_init__(self) -> None:
        if not (0 <= self.crr < 1 and 0 <= self.slr < 1):
            raise ValueError("CRR and SLR are fractions of NDTL")
        if not 0 < self.crr_daily_min_share <= 1:
            raise ValueError("the daily CRR minimum is a share of the requirement")
