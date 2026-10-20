"""RBI rules the bank universe obeys, each tied to the document it was checked against.

Rates that change with policy (CRR, SLR, repo, SDF, MSF) are *not* defaults here: the simulator
reads today's values from RBI's published data. What lives here are rule parameters and the
dated history the fits need (the CRR schedule, the reporting-fortnight calendar), each with a
source. The one exception is the lending limit: RBI's directions set no lending cap, so
participants use board-approved internal limits; the values here are an assumption.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


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
    Citation(
        "Reporting fortnight: the 1st to the 15th and the 16th to the last day of each month from "
        "16 Dec 2025, after a transition period of 13-15 Dec 2025; before that, Saturday to the "
        "second following Friday.",
        "RBI/2025-26/148, DOR.RET.REC.354/12.01.001/2025-26 (11 Dec 2025)",
        "https://rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx?Id=13224",
        _VERIFIED,
    ),
    Citation(
        "CRR raised from 4.00% to 4.50% of NDTL from the fortnight beginning 21 May 2022.",
        "RBI/2022-23/46, DOR.RET.REC.33/12.01.001/2022-23 (4 May 2022)",
        "https://www.rbi.org.in/scripts/FS_Notification.aspx?Id=12313&fn=2&Mode=0",
        _VERIFIED,
    ),
    Citation(
        "CRR 4.25% from the fortnight beginning 14 Dec 2024 and 4.00% from 28 Dec 2024.",
        "RBI/2024-25/95, DoR.RET.REC.52/12.01.001/2024-25 (6 Dec 2024)",
        "https://www.rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx?Id=12754",
        _VERIFIED,
    ),
    Citation(
        "CRR 3.75%, 3.5%, 3.25% and 3.0% from the fortnights beginning 6 Sep, 4 Oct, 1 Nov and "
        "29 Nov 2025.",
        "RBI/2025-26/46, DoR.RET.REC.23/12.01.001/2025-26 (6 Jun 2025)",
        "https://www.rbi.org.in/scripts/FS_Notification.aspx?Id=12858",
        _VERIFIED,
    ),
    Citation(
        "Incremental CRR of 10% on the increase in NDTL between 19 May and 28 Jul 2023, released "
        "25% on 9 Sep, 25% on 23 Sep and 50% on 7 Oct 2023.",
        "Press release 2023-2024/886 (8 Sep 2023), Incremental Cash Reserve Ratio (I-CRR): Review",
        "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=56336",
        _VERIFIED,
    ),
    Citation(
        "Variable rate reverse repo: bids ranked by rate ascending, cut-off at the notified "
        "amount, successful bids at their own rates, pro rata at the cut-off, bids at or above "
        "the repo rate rejected, minimum bid Rs 1 crore.",
        "Press release 2019-2020/1947 (13 Feb 2020), operational guidelines",
        "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=49399",
        _VERIFIED,
    ),
    Citation(
        "Variable rate repo: bids ranked by rate descending, cut-off at the notified amount, "
        "successful bids at their own rates, pro rata at the cut-off, bids at or below the repo "
        "rate rejected.",
        "Press release 2021-2022/1572 (20 Jan 2022), operational guidelines",
        "https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=53127",
        _VERIFIED,
    ),
)

# VERIFY: CRR in force from each fortnight start, per the circulars above (checked 2026-10-20).
# The first row is the rate RBI/2022-23/46 raised "from 4.00 percent"; it covers the data window
# from 8 Apr 2022 (the SDF's introduction). Today's CRR always comes from RBI's homepage.
CRR_SCHEDULE: tuple[tuple[date, float], ...] = (
    (date(2022, 4, 1), 0.0400),
    (date(2022, 5, 21), 0.0450),
    (date(2024, 12, 14), 0.0425),
    (date(2024, 12, 28), 0.0400),
    (date(2025, 9, 6), 0.0375),
    (date(2025, 10, 4), 0.0350),
    (date(2025, 11, 1), 0.0325),
    (date(2025, 11, 29), 0.0300),
)

ICRR_PERIOD: tuple[date, date] = (date(2023, 8, 10), date(2023, 10, 20))
"""When the reported requirement included the temporary I-CRR (announced 10 Aug 2023, released
by 7 Oct 2023), with two weeks' margin; requirement ÷ CRR overstates NDTL then."""

HALF_MONTH_FORTNIGHTS_FROM = date(2025, 12, 16)
FORTNIGHT_TRANSITION: tuple[date, date] = (date(2025, 12, 13), date(2025, 12, 15))
_SATURDAY_FORTNIGHT = date(2025, 11, 29)
"""A Saturday that began a reporting fortnight (the one the CRR reached 3.0%)."""


def crr_on(day: date) -> float:
    """CRR (fraction of NDTL) in force on a day, from the dated schedule.

    Equation:
        CRR(d) = CRRₖ for the last schedule entry with startₖ ≤ d
    """
    if day < CRR_SCHEDULE[0][0]:
        raise ValueError(f"no CRR on record before {CRR_SCHEDULE[0][0]}")
    return next(rate for start, rate in reversed(CRR_SCHEDULE) if start <= day)


def fortnight(day: date) -> tuple[date, date]:
    """The CRR reporting fortnight containing a day: (first day, last day), inclusive.

    Equation:
        from 16 Dec 2025:  [1st, 15th] or [16th, last day of the month]
        13-15 Dec 2025:    the transition period
        earlier:           start = S₀ + 14·⌊(d − S₀)/14⌋,  end = start + 13   (S₀ a Saturday start)
    """
    if day >= HALF_MONTH_FORTNIGHTS_FROM:
        if day.day <= 15:
            return day.replace(day=1), day.replace(day=15)
        last = calendar.monthrange(day.year, day.month)[1]
        return day.replace(day=16), day.replace(day=last)
    if FORTNIGHT_TRANSITION[0] <= day <= FORTNIGHT_TRANSITION[1]:
        return FORTNIGHT_TRANSITION
    start = _SATURDAY_FORTNIGHT + timedelta(days=14 * ((day - _SATURDAY_FORTNIGHT).days // 14))
    return start, start + timedelta(days=13)


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

    def __post_init__(self) -> None:
        if not (0 <= self.crr < 1 and 0 <= self.slr < 1):
            raise ValueError("CRR and SLR are fractions of NDTL")
        if not 0 < self.crr_daily_min_share <= 1:
            raise ValueError("the daily CRR minimum is a share of the requirement")
