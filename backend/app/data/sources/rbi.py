"""Reserve Bank of India: current policy rates (homepage) and the daily Money Market Operations.

The homepage box carries the policy repo, SDF and MSF rates, Bank Rate, CRR and SLR in force on
the day it is read. Each day's "Money Market Operations as on <date>" press release carries the
call money weighted average rate (WACR, RBI's operating target) with its range, TREPS (triparty
repo) and market repo — "based on RBI / CCIL" per the release's own footnote — plus RBI's
operations outstanding that day, net liquidity and the banks' cash-reserve position. Older
releases are reached through the press-release archive, an ASP.NET form posted per month.

The homepage also shows FBIL's INR/USD reference rate "as at 1.00pm of <date>", which is kept
with that date: FBIL's own public data runs about a week behind. Its T-bill cut-offs are not
taken, as they carry no auction date; FBIL's T-bill benchmarks are used instead.
"""

import contextlib
import html
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from app.data.catalog import IN_MMO_SERIES, IN_RBI_SERIES
from app.data.http import FetchedBody, Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy

HOME_URL = "https://www.rbi.org.in/"
PRESS_URL = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
INDIA = ZoneInfo("Asia/Kolkata")

_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _text(fragment: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAGS.sub(" ", fragment))).strip()


def _number(cell: str) -> float | None:
    cleaned = cell.replace(",", "").replace("%", "").strip()
    if cleaned in ("", "-", "–"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _long_date(text: str) -> date | None:
    match = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", text)
    if not match:
        return None
    try:
        return (
            datetime.strptime(f"{match[1]} {match[2]} {match[3]}", "%B %d %Y")
            .replace(tzinfo=UTC)
            .date()
        )
    except ValueError:
        return None


def _cell_date(cell: str) -> date | None:
    """A date as the releases write it: "October 24, 2023" or, in some months, "24/10/2023"."""
    if match := re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", cell.strip()):
        try:
            return date(int(match[3]), int(match[2]), int(match[1]))
        except ValueError:
            return None
    return _long_date(cell)


# ----------------------------------------------------------------------- homepage

_HOME_FIELDS: dict[str, str] = {
    "repo": r"Policy Repo Rate\s*:\s*([\d.]+)\s*%",
    "sdf": r"Standing Deposit Facility Rate\s*:\s*([\d.]+)\s*%",
    "msf": r"Marginal Standing Facility Rate\s*:\s*([\d.]+)\s*%",
    "bank_rate": r"Bank Rate\s*:\s*([\d.]+)\s*%",
    "fixed_reverse_repo": r"Fixed Reverse Repo Rate\s*:\s*([\d.]+)\s*%",
    "crr": r"CRR\s*:\s*([\d.]+)\s*%",
    "slr": r"SLR\s*:\s*([\d.]+)\s*%",
}


@dataclass(frozen=True, slots=True)
class HomeRates:
    values: dict[str, float]
    """Policy rates and reserve ratios (per cent), plus ``usdinr`` when it is dated."""
    dated: dict[str, date]
    """Dates of values the page dates itself (the reference rate); the rest are in force today."""


def parse_home(content: bytes) -> HomeRates:
    """The homepage's current-rates box."""
    plain = _text(content.decode("utf-8", errors="replace"))
    values = {
        key: float(m[1])
        for key, pattern in _HOME_FIELDS.items()
        if (m := re.search(pattern, plain))
    }
    if "repo" not in values:
        raise SourceError("rbi: the homepage has no policy repo rate (layout changed?)")
    dated: dict[str, date] = {}
    usd = re.search(r"INR\s*/\s*1 USD\s*:\s*([\d.]+)", plain)
    as_at = re.search(r"\(As at [^)]*? of ([A-Z][a-z]+ \d{1,2}, \d{4})\)", plain)
    if usd and as_at and (when := _long_date(as_at[1])) is not None:
        values["usdinr"], dated["usdinr"] = float(usd[1]), when
    return HomeRates(values, dated)


# ----------------------------------------------------------------------- Money Market Operations

Section = Literal["overnight", "term", "today", "outstanding", "other"]


@dataclass(slots=True)
class MmoReport:
    as_of: date
    values: dict[str, float] = field(default_factory=dict)
    dated: dict[str, date] = field(default_factory=dict)
    """Dates of values RBI reports "as on" another day (reserves, durable liquidity)."""


def _rows(fragment: str) -> list[list[str]]:
    return [
        [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", fragment, re.S | re.I)
    ]


def _segment(values: dict[str, float], key: str, cells: list[str]) -> None:
    """Money-market row: label | volume | weighted average rate | low-high range."""
    if len(cells) < 4:
        return
    if (volume := _number(cells[1])) is not None:
        values[f"{key}_volume"] = volume
    if (rate := _number(cells[2])) is not None:
        values[f"{key}_rate"] = rate
    if match := re.fullmatch(r"([\d.]+)\s*-\s*([\d.]+)", cells[3]):
        values[f"{key}_low"], values[f"{key}_high"] = float(match[1]), float(match[2])


def _amounts(cells: list[str]) -> list[float]:
    return [n for c in cells if (n := _number(c)) is not None]


_AUCTION_DATE = re.compile(r"^[A-Z][a-z]{2}, \d{2}/\d{2}/\d{4}$")

# RBI operations by row label. Injections: MSF, variable rate repo (VRR) and the long-term repo
# family (LTRO, TLTRO, SLTRO); absorptions: SDF and variable rate reverse repo (VRRR).
_FACILITIES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\d+\.\s*MSF\b"), "msf"),
    (re.compile(r"\d+\.\s*SDF\b"), "sdf"),
    (re.compile(r"\d+\.\s*.*Long[- ]Term Repo"), "ltro"),
    (re.compile(r"\([a-z]\)\s*Reverse Repo"), "vrrr"),
    (re.compile(r"\([a-z]\)\s*Repo"), "vrr"),
)
_UNDATED_ROWS = (
    ("D. Standing Liquidity Facility", "slf_amount"),
    ("F. Net liquidity injected", "net_liquidity"),
    ("(ii) Average daily cash reserve", "crr_requirement"),
)
_DATED_ROWS = (
    ("(i) Cash balances with RBI", "crr_balance"),
    ("H. Government of India Surplus", "gov_surplus_cash"),
    ("I. Net durable liquidity", "durable_liquidity"),
)


def _legs(label: str, cells: list[str], facility: str | None) -> tuple[str | None, list[str]]:
    """The facility an operations row belongs to, and its cells from the auction date on."""
    if (
        kind := next((key for pattern, key in _FACILITIES if pattern.match(label)), None)
    ) is not None:
        return kind, cells[1:]
    if facility and _AUCTION_DATE.match(label):
        return facility, cells  # a further operation: RBI spans the label cell over it ...
    if facility and not label and len(cells) > 1 and _AUCTION_DATE.match(cells[1]):
        return facility, cells[1:]  # ... or leaves the label cell empty
    return None, []


def parse_mmo(content: bytes) -> MmoReport:
    """One "Money Market Operations as on <date>" release (amounts ₹ crore, rates per cent).

    Facility amounts are what is outstanding on the day: today's operations plus earlier ones
    not yet matured (a Friday's three-day SDF still counts on Sunday). Summed that way, RBI's
    net liquidity row F equals MSF + VRR + long-term repos + SLF − SDF − VRRR. There is a release
    for every calendar day; on holidays the money markets are shut and show no rates.
    """
    page = content.decode("utf-8", errors="replace")
    title = re.search(r"Money Market Operations as on\s+([A-Z][a-z]+ \d{1,2}, \d{4})", _text(page))
    if not title:
        raise SourceError("rbi: not a Money Market Operations release")
    as_of = _long_date(title[1])
    if as_of is None:
        raise SourceError("rbi: unreadable release date")
    report = MmoReport(as_of)
    values = report.values
    section: Section = "other"
    facility: str | None = None
    for cells in _rows(page):
        if not any(cells):
            continue
        label = cells[0]
        if label.startswith("A. Overnight Segment"):
            section = "overnight"
            _segment(values, "overnight", cells)
        elif label.startswith("B. Term Segment"):
            section = "term"
        elif label.startswith("I. Today"):
            section, facility = "today", None
        elif label.startswith("II. Outstanding"):
            section, facility = "outstanding", None
        elif section == "overnight":
            for prefix, key in (
                ("I. Call Money", "call"),
                ("II. Triparty Repo", "treps"),
                ("III. Market Repo", "market_repo"),
            ):
                if label.startswith(prefix):
                    _segment(values, key, cells)
        elif section == "term":
            for prefix, key in (("I. Notice Money", "notice"), ("II. Term Money", "term")):
                if label.startswith(prefix):
                    _segment(values, key, cells)
        elif section in ("today", "outstanding"):
            # legs: auction date | tenor | maturity | amount | rate
            facility, legs = _legs(label, cells, facility)
            if facility and len(legs) >= 5 and (amount := _number(legs[3])) is not None:
                values[f"{facility}_amount"] = values.get(f"{facility}_amount", 0.0) + amount
                rate = _number(legs[4])
                if section == "today" and facility in ("msf", "sdf") and rate is not None:
                    values[f"{facility}_rate"] = rate

        for prefix, key in _UNDATED_ROWS:
            if label.startswith(prefix) and (amounts := _amounts(cells[1:])):
                values[key] = amounts[-1]
        for prefix, key in _DATED_ROWS:
            if label.startswith(prefix) and (amounts := _amounts(cells[1:])):
                when = next((d for c in cells[1:] if (d := _cell_date(c)) is not None), None)
                if when is not None:
                    values[key], report.dated[key] = amounts[-1], when
    if "overnight_volume" not in values:
        raise SourceError(f"rbi: no overnight money-market segment in the release for {as_of}")
    return report


def parse_release_links(content: bytes) -> dict[date, str]:
    """MMO release ids by date from a press-release listing or archive page."""
    links: dict[date, str] = {}
    for prid, title in re.findall(
        r"prid=(\d+)>\s*Money Market Operations as on ([^<]+)<", content.decode("utf-8", "replace")
    ):
        when = _long_date(title)
        if when is not None:
            links[when] = prid
    return links


def archive_form(listing_page: bytes, year: int, month: int) -> dict[str, str]:
    """Form fields that make the press-release page list one month (the site's GetYearMonth)."""
    page = listing_page.decode("utf-8", errors="replace")
    hidden = dict(
        re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]+" value="([^"]*)"', page)
    )
    form = {k: html.unescape(v) for k, v in hidden.items() if k.startswith("__")}
    if "__VIEWSTATE" not in form:
        raise SourceError("rbi: the press-release page has no ASP.NET form state")
    return {**form, "hdnYear": str(year), "hdnMonth": str(month), "UsrFontCntr$btn": ""}


# ----------------------------------------------------------------------- adapter


class RbiAdapter:
    """Homepage rates plus the MMO releases in [start, end] (the latest listing when no start)."""

    source = "rbi"

    def __init__(self, fetcher: Fetcher, *, pause_s: float = 1.0) -> None:
        self.fetcher = fetcher
        self.pause_s = pause_s
        """Seconds before each archive download, to crawl the archive politely."""
        self.rbi_specs = {s.remote: s for s in IN_RBI_SERIES}
        self.mmo_specs = {s.remote: s for s in IN_MMO_SERIES}

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        outcome = FetchOutcome()
        try:
            outcome.frames.extend(self._home())
        except SourceError as exc:
            outcome.errors["homepage"] = str(exc)
        try:
            outcome.frames.extend(self._mmo(start, end, outcome))
        except SourceError as exc:
            outcome.errors["mmo"] = str(exc)
        if series_ids is not None:
            outcome.frames = [f for f in outcome.frames if f.spec.series_id in series_ids]
        if not outcome.frames and outcome.errors:
            raise SourceError(f"rbi: nothing could be fetched: {outcome.errors}")
        return outcome

    def _home(self) -> list[SeriesFrame]:
        body = self.fetcher.get(self.source, HOME_URL)
        provenance = Provenance(self.source, body.url, body.fetched_at, body.from_cache)
        in_force = body.fetched_at.astimezone(INDIA).date()
        rates = parse_home(body.content)
        return [
            SeriesFrame(spec, tidy([(rates.dated.get(remote, in_force), value)]), provenance)
            for remote, value in rates.values.items()
            if (spec := self.rbi_specs.get(remote)) is not None
        ]

    def _listing(self, start: date | None, end: date | None) -> tuple[dict[date, str], bool]:
        """Release ids by date, and whether the listing is a stale fallback copy.

        The press-release page lists only the latest days (about ten), so each month that the
        requested range reaches before that is listed through the archive form.
        """
        first = self.fetcher.get(self.source, PRESS_URL)
        links = parse_release_links(first.content)
        if start is None:
            return links, first.from_cache
        covered = min(links, default=None)
        last = end or first.fetched_at.astimezone(INDIA).date()
        month = date(start.year, start.month, 1)
        while month <= last:
            if covered is None or max(start, month) < covered:
                time.sleep(self.pause_s)
                form = archive_form(first.content, month.year, month.month)
                page = self.fetcher.post(
                    self.source, PRESS_URL, form, key_fields=("hdnYear", "hdnMonth")
                )
                links.update(parse_release_links(page.content))
            month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
        return {d: p for d, p in links.items() if start <= d <= last}, first.from_cache

    def _release(self, prid: str) -> tuple[FetchedBody, MmoReport]:
        """A release never changes once published, so a copy saved by an earlier crawl is parsed
        instead of downloaded again, unless it does not parse (say, a saved error page)."""
        params = {"prid": prid}
        if (saved := self.fetcher.saved(self.source, PRESS_URL, params)) is not None:
            with contextlib.suppress(SourceError):
                return saved, parse_mmo(saved.content)
        time.sleep(self.pause_s)
        body = self.fetcher.get(self.source, PRESS_URL, params)
        return body, parse_mmo(body.content)

    def _mmo(
        self, start: date | None, end: date | None, outcome: FetchOutcome
    ) -> list[SeriesFrame]:
        points: dict[str, list[tuple[date, float]]] = {}
        latest: FetchedBody | None = None
        links, stale = self._listing(start, end)
        for when, prid in sorted(links.items()):
            try:
                latest, report = self._release(prid)
            except SourceError as exc:
                outcome.errors[f"mmo {when}"] = str(exc)
                continue
            for key, value in report.values.items():
                points.setdefault(key, []).append((report.dated.get(key, report.as_of), value))
        if latest is None:
            return []
        provenance = Provenance(self.source, latest.url, latest.fetched_at, stale)
        return [
            SeriesFrame(self.mmo_specs[key], tidy(values), provenance)
            for key, values in points.items()
            if key in self.mmo_specs
        ]
