"""How India's overnight money markets trade, clear and settle: what the CCIL panel draws.

The rates and volumes are the simulated market's; the plumbing below is from RBI and CCIL,
each claim tied to the page it was checked against (2026-10-21).
"""

from dataclasses import dataclass
from datetime import time
from typing import TYPE_CHECKING, Any

from sovereign_engine.india.rules import CALL_MARKET_HOURS, REPO_MARKET_HOURS

if TYPE_CHECKING:
    from app.sim.india_market import IndiaMarket


@dataclass(frozen=True, slots=True)
class Source:
    claim: str
    document: str
    url: str


SOURCES: tuple[Source, ...] = (
    Source(
        "NDS-CALL is an electronic request-for-quote platform owned by RBI and managed by "
        "Clearcorp, a wholly owned subsidiary of CCIL. CROMS (market repo) and TREPS (tri-party "
        "repo) are Clearcorp's anonymous order-matching systems for dealing against G-secs.",
        "CCIL, Clearcorp Dealing Systems",
        "https://www.ccilindia.com/clearcorp-dealing-systems",
    ),
    Source(
        "Call money is settled bilaterally through RTGS, throughout the day. Market repo and "
        "TREPS are settled through CCIL, which acts as central counterparty, with multilateral "
        "netting of funds and securities.",
        "RBI, Report of the Working Group on Comprehensive Review of Trading and Settlement "
        "Timings of Markets Regulated by the Reserve Bank (draft)",
        "https://www.rbi.org.in/scripts/PublicationReportDetails.aspx?ID=935",
    ),
    Source(
        "TREPS trades flow from Clearcorp to CCIL, the tri-party agent, which novates them and "
        "nets them for funds settlement with outright and market repo trades. The borrower's "
        "securities move from its GILT account at CCIL to CCIL's settlement account, and on to "
        "the lender's once funds have settled at RBI.",
        "CCIL, Triparty Repo: Clearing and Settlement Procedure",
        "https://www.ccilindia.com/web/ccil/tripartyclearingsettlement",
    ),
    Source(
        "NDS-CALL is the platform for executing and reporting call, notice and term money; deals "
        "done over the counter are reported on it within 15 minutes. Only banks and primary "
        "dealers may take part.",
        "RBI/2021-22/61, Call, Notice and Term Money Markets Directions, 2021",
        "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12120",
    ),
    Source(
        "Call money trades from 9:00 AM to 7:00 PM from 1 Jul 2025; market repo and TREPS from "
        "9:00 AM to 4:00 PM from 1 Aug 2025.",
        "RBI Bulletin, State of the Economy (23 Jul 2025), footnote 15",
        "https://www.rbi.org.in/Scripts/BS_ViewBulletin.aspx?Id=23515",
    ),
)


@dataclass(frozen=True, slots=True)
class Segment:
    key: str
    """The simulator's name for the segment: call, treps or market_repo."""
    name: str
    platform: str
    dealing: str
    collateral: str | None
    counterparty: str
    settlement: str
    hours: tuple[time, time]
    sources: tuple[int, ...]
    """Indexes into SOURCES."""


SEGMENTS: tuple[Segment, ...] = (
    Segment(
        "call",
        "Call money",
        "NDS-CALL",
        "Request for quote between named banks (or over the counter, reported within 15 minutes)",
        None,
        "The other bank: unsecured, so each lender carries its borrower's credit risk, which is "
        "why RBI caps call borrowing",
        "Bilaterally through RTGS, during the day",
        CALL_MARKET_HOURS,
        (0, 1, 3, 4),
    ),
    Segment(
        "treps",
        "TREPS (tri-party repo)",
        "TREPS",
        "Anonymous order matching",
        "Government securities, held and allocated by CCIL as tri-party agent",
        "CCIL, as central counterparty: each trade is novated to it",
        "Netted by CCIL with outright and market repo trades; funds settle at RBI, securities "
        "move between GILT accounts at CCIL",
        REPO_MARKET_HOURS,
        (0, 1, 2, 4),
    ),
    Segment(
        "market_repo",
        "Market repo",
        "CROMS",
        "Anonymous order matching",
        "Government securities, sold and bought back",
        "CCIL, as central counterparty",
        "Netted by CCIL with outright trades, funds and securities together",
        REPO_MARKET_HOURS,
        (0, 1, 4),
    ),
)


def _hours(span: tuple[time, time]) -> list[str]:
    return [t.strftime("%H:%M") for t in span]


def ccil_panel(m: "IndiaMarket") -> dict[str, Any]:
    """Today's call, TREPS and market repo, with how each one clears and settles."""
    call = m.call_panel()
    rates = {"call": m.wacr(), **m.segment_rates()}
    volumes = call["segment_volumes"]
    snap = m.snapshot()
    return {
        "segments": [
            {
                "key": s.key,
                "name": s.name,
                "platform": s.platform,
                "dealing": s.dealing,
                "collateral": s.collateral,
                "counterparty": s.counterparty,
                "settlement": s.settlement,
                "hours": _hours(s.hours),
                "sources": list(s.sources),
                "rate": rates[s.key],
                "volume": volumes[s.key],
            }
            for s in SEGMENTS
        ],
        "also_on_nds_call": {
            "notice": {"rate": rates["notice"], "volume": volumes["notice"]},
            "term": {"rate": rates["term"], "volume": volumes["term"]},
        },
        "repo": m.repo,
        "time": snap["time"],
        "session_open": snap["session_open"],
        "model": (
            "Rates and volumes are the simulated day's: TREPS and market repo trade at WACR "
            "plus, and in proportion to call volume by, their medians over the last year of "
            "RBI's daily releases."
        ),
        "sources": [{"claim": s.claim, "document": s.document, "url": s.url} for s in SOURCES],
    }
