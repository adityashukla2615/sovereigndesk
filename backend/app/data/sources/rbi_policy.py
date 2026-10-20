"""RBI's monetary-policy record from its press releases, for the MPC predictor.

* Decisions: every policy repo rate decision since April 2014: the MPC's resolutions (from
  October 2016), the Governor's bi-monthly statements before them, and his intermeeting
  statements (15 Jan and 4 Mar 2015). The rate is read from the sentence that sets it ("keep the
  policy repo rate ... unchanged at 6.50 per cent", "reduce ... by 25 basis points ... to 6.25
  per cent").
* Meeting schedules: "Meeting Schedule of the Monetary Policy Committee for <year>" and its
  revisions list each meeting's days (the decision comes on the last); a notice that moves a
  meeting gives the new days after the old ones ("rescheduled to August 4 - 6, 2025", "will now
  be held on June 4-6, 2018").
* T-bills: the weekly 91-day auction's cut-off yield ("YTM: 6.2735%"), from per-tenor result
  releases until 2021 and the all-tenor "Treasury Bills: Full Auction Result" since.
* Money markets before each decision: WACR, call volume, the net liquidity RBI injected and the
  banks' fortnightly CRR requirement, from the Money Market Operations releases of every era.
  Amounts were in ₹ billion until 2019 (converted to ₹ crore here), and before mid-2019 the
  release does not print net liquidity, so it is summed from the LAF legs as RBI's own footnote
  later defines it: repo + MSF + SLF − reverse repo.

* Foreign exchange reserves: the weekly "Reserve Bank of India – Bulletin Weekly Statistical
  Supplement – Extract", table 2: total reserves, foreign currency assets and gold (US$
  million) as on the Friday before, for the linkage's calibration.
* Lending rates: the monthly "Lending and Deposit Rates of Scheduled Commercial Banks" (from July
  2021) states the banks' 1-year median MCLR in its highlights ("declined to 8.61 per cent in
  September 2026 from 8.70 per cent in August 2026"), for the business impact (Module E).

Releases are listed month by month through the press-release archive (an ASP.NET form). A
release never changes once published, so a saved copy is parsed instead of downloaded again,
and so is a month's listing saved after the month ended.
"""

import contextlib
import html
import re
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.data.catalog import IN_RBI_POLICY_SERIES, SeriesSpec
from app.data.http import FetchedBody, Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy
from app.data.sources.rbi import INDIA, PRESS_URL, archive_month

_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip
_MONTH = "(" + "|".join(_MONTHS) + ")"
MMO_WINDOW_DAYS = 14
"""Calendar days of Money Market Operations releases read before each decision."""
MEETING_GAP_DAYS = 14
"""Meetings are about two months apart (an additional one a month after the last), so a day a
later release gives within this many days of a known meeting moves that meeting."""


def _text(fragment: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAGS.sub(" ", fragment))).strip()


@dataclass(frozen=True, slots=True)
class Listing:
    day: date
    """The release date the archive files it under."""
    prid: str
    title: str


def parse_listing(content: bytes) -> list[Listing]:
    """Every release on a press-release listing or archive page, with its date header."""
    page = content.decode("utf-8", "replace")
    out: list[Listing] = []
    day: date | None = None
    pattern = r'class="tableheader"[^>]*><b>([A-Z][a-z]{2} \d{2}, \d{4})|prid=(\d+)>([^<]+)<'
    for match in re.finditer(pattern, page):
        if match[1]:
            day = datetime.strptime(match[1], "%b %d, %Y").replace(tzinfo=UTC).date()
        elif day is not None:
            out.append(Listing(day, match[2], _text(match[3])))
    return out


# ----------------------------------------------------------------------- decisions

_ANNOUNCEMENT = re.compile(
    rf"(?i)\bon (monday|tuesday|wednesday|thursday|friday|{_MONTH})|\bat \d|\bto announce"
)


def is_decision_title(title: str) -> bool:
    """A release that may carry a policy repo rate decision (pre-announcements excluded)."""
    t = title.lower()
    if t.startswith("minutes") or "meeting schedule" in t or "rescheduled" in t:
        return False
    if "resolution of the monetary policy committee" in t:
        return True
    if "monetary policy statement" in t:
        return not _ANNOUNCEMENT.search(title)
    return t.startswith("statement by") and "monetary policy" in t


@dataclass(frozen=True, slots=True)
class Decision:
    repo: float
    """The policy repo rate after the decision (per cent)."""
    previous: float | None
    """The rate before, when the sentence states it ("from 6.5 per cent")."""
    change_bp: float | None
    """The stated size of the move ("by 25 basis points"); 0 for an unchanged rate."""


_VERB = r"(keep|maintain|retain|leave|reduce|increase|decrease|raise|cut|hike)"
_HOLDS = ("keep", "maintain", "retain", "leave")


def parse_decision(content: bytes) -> Decision | None:
    """The repo rate decision in a policy release, or None when the release sets none."""
    text = _text(content.decode("utf-8", "replace"))
    for sentence in re.split(r"(?<=[.;])\s+", text):
        verb = re.search(rf"(?i)\b{_VERB}\w*\s+the policy repo rate", sentence)
        if not verb:
            continue
        tail = sentence[verb.start() :]
        unchanged = re.search(r"(?i)\b(?:unchanged )?at ([\d.]+)\s*per\s*cent", tail)
        moved = re.search(r"(?i)\bto ([\d.]+)\s*per\s*cent", tail)
        if verb[1].lower() in _HOLDS:  # "keep ... unchanged at", "maintain ... at"
            if unchanged is None:
                continue
            return Decision(float(unchanged[1]), float(unchanged[1]), 0.0)
        if moved is None:
            continue
        before = re.search(r"(?i)\bfrom ([\d.]+)\s*per\s*cent", tail)
        size = re.search(r"(?i)\bby (\d+)\s*(?:basis points|bps)", tail)
        return Decision(
            float(moved[1]),
            float(before[1]) if before else None,
            float(size[1]) if size else None,
        )
    return None


# ----------------------------------------------------------------------- schedules

_MEETING = re.compile(
    rf"{_MONTH}\s+(\d{{1,2}})(?:\s*(?:,|and|to|-|–|&)\s*(\d{{1,2}}))*,\s*(\d{{4}})"
)


def is_schedule_title(title: str) -> bool:
    """A yearly schedule, a revision or rescheduling, or a notice of one meeting's dates."""
    t = title.lower()
    return "meeting schedule" in t or (
        "meeting of the monetary policy committee" in t and not t.startswith("minutes")
    )


def _last_days(text: str) -> list[date]:
    out = []
    for match in _MEETING.finditer(text):
        last = match[3] or match[2]
        with contextlib.suppress(ValueError):
            out.append(date(int(match[4]), _MONTHS.index(match[1]) + 1, int(last)))
    return out


_PHRASE = rf"{_MONTH}\s+\d{{1,2}}[^.;]*?,\s*\d{{4}}"
_NOT_A_MEETING = re.compile(rf"(?i)\b(?:dated|from|commencing on|instead of(?: on)?)\s+{_PHRASE}")
"""Dates in a notice that are not (new) decision days: references to earlier releases, the
old dates a meeting moved from, and the first day of a meeting."""
_MOVED = re.compile(r"(?i)reschedul|now be held")
"""Where a notice that moves a meeting comes to the new dates; the old ones come before."""


def parse_schedule(content: bytes) -> list[date]:
    """Decision days (each meeting's last day) from a schedule release or a notice: the date
    table of a yearly schedule, else the dates in the notice's text ("will be issued on October
    5, 2018", "rescheduled ... to February 8-10, 2022")."""
    page = content.decode("utf-8", "replace")
    days: list[date] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I):
        for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S | re.I):
            cell_text = _text(cell)
            lower = cell_text.lower()
            if len(cell_text) < 60 and "dated" not in lower and not lower.startswith("date"):
                days.extend(_last_days(cell_text))
    if not days:
        text = _text(page)
        start = text.find("Date :")
        # The notice ends at its own release number, the last "Press Release:" before the
        # archive navigation; earlier ones are references ("As announced in ... Press Release").
        end = text.rfind("Press Release:", start, start + 3000)
        notice = text[start : end if end > start else start + 2000]
        notice = re.sub(r"^Date : [A-Z][a-z]{2} \d{2}, \d{4}", " ", notice)
        if moves := list(_MOVED.finditer(notice)):
            notice = notice[moves[-1].end() :]  # none left: "the dates will be announced"
        days = _last_days(_NOT_A_MEETING.sub(" ", notice))
    return sorted(set(days))


def merge_meetings(releases: Iterable[list[date]]) -> set[date]:
    """Decision days from schedule releases in the order RBI issued them: a day within
    ``MEETING_GAP_DAYS`` of one already known moves that meeting (a postponement, a revised
    schedule), so the old day is dropped."""
    meetings: set[date] = set()
    for days in releases:
        for day in days:
            meetings = {m for m in meetings if abs((m - day).days) > MEETING_GAP_DAYS}
            meetings.add(day)
    return meetings


# ----------------------------------------------------------------------- T-bills


_YTM = r"YTM\s*[:\-–]?\s*([\d.]+)\s*%"
"""A cut-off yield as the releases print it: "(YTM:6.2735%)", "(YTM - 8.3946 %)"."""


def is_tbill_title(title: str) -> bool:
    """A 91-day result release, or one for all tenors (since 2021)."""
    t = title.lower().replace("–", "-")
    if "auction result" not in t or "treasury bill" not in t:
        return False
    return t.startswith(("91-day", "91 day")) or t.startswith("treasury bill")


def parse_tbill_cutoff(content: bytes) -> float | None:
    """The 91-day bill's cut-off yield (per cent), or None if the release has no 91-day bill.

    A per-tenor release prints one "YTM"; the all-tenor table has a column per tenor and the
    cut-off yields in the row under the cut-off prices, in the header's column order. A tenor
    whose bids RBI rejected prints "-" there."""
    page = content.decode("utf-8", "replace")
    rows = [
        [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I)
    ]
    tenors: list[str] | None = None
    for cells in rows:
        found = [m[1] for c in cells if (m := re.fullmatch(r"(?i)(\d{2,3})[- ]?Days?", c))]
        if found:
            tenors = found  # "91-Day | 182-Day | 364-Day" or "91 Days | 182 Days | 364 Days"
            continue
        if tenors is not None and any(re.search(_YTM, c) for c in cells):
            if "91" not in tenors or len(cells) < len(tenors):
                return None
            # The tenor columns are the row's last cells (a label may come first).
            ytm = re.search(_YTM, cells[len(cells) - len(tenors) + tenors.index("91")])
            return float(ytm[1]) if ytm else None
    text = _text(page)
    if tenors is None and re.search(r"(?i)\b91[- ]Days? Treasury Bills?\b", text):
        first = re.search(_YTM, text)
        return float(first[1]) if first else None
    return None


# ----------------------------------------------------------------------- forex reserves


def is_wss_title(title: str) -> bool:
    return "weekly statistical supplement" in title.lower()


@dataclass(frozen=True, slots=True)
class Reserves:
    """Foreign exchange reserves (US$ million) as on one day."""

    as_of: date
    total: float
    fca: float
    """Foreign currency assets."""
    gold: float


_RESERVE_ROWS = {"total reserves": "total", "foreign currency assets": "fca", "gold": "gold"}
_AS_ON = re.compile(r"As on\s+([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s*(\d{4})")
""""As on June 20, 2025", "As on April 1 2016" and, since mid-2025, "As on Aug. 29, 2025"."""


def parse_reserves(content: bytes) -> Reserves:
    """Table 2 of a Weekly Statistical Supplement extract: the reserves "As on" a day, in US$
    million (the second column; the first is ₹, in billion until 2020 and in crore since)."""
    page = content.decode("utf-8", "replace")
    as_of: date | None = None
    values: dict[str, float] = {}
    started = False
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I):
        cells = [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        joined = " ".join(cells)
        if re.match(r"(?i)\d\.\s*Foreign Exchange Reserves", joined):
            started = True
            continue
        if not started:
            continue
        if re.match(r"\d\.\s+[A-Z]", joined):
            break  # the next table
        if as_of is None and (on := _AS_ON.search(joined)):
            month = next((i for i, m in enumerate(_MONTHS) if m.startswith(on[1][:3])), None)
            if month is not None:
                as_of = date(int(on[3]), month + 1, int(on[2]))
            continue
        label = re.sub(r"^[\d.]+\s*", "", cells[0] if cells else "").rstrip(" #*").lower()
        if (key := _RESERVE_ROWS.get(label)) and len(cells) >= 3:
            usd = _number(cells[2].replace("–", "-"))
            if usd is not None:
                values[key] = usd
    if as_of is None or set(values) != set(_RESERVE_ROWS.values()):
        raise SourceError("rbi_policy: no foreign exchange reserves table in the release")
    return Reserves(as_of, values["total"], values["fca"], values["gold"])


# ----------------------------------------------------------------------- lending rates


def is_lending_rates_title(title: str) -> bool:
    return title.lower().startswith("lending and deposit rates of scheduled commercial banks")


_MCLR = re.compile(r"(?i)median Marginal Cost of Funds?[- ]based Lending Rate \(MCLR\)")
_PER_CENT_IN = re.compile(rf"([\d.]+)\s*per\s*cent in {_MONTH},? (\d{{4}})")


def parse_mclr(content: bytes) -> dict[date, float]:
    """The 1-year median MCLR by month (dated the month's first day) from a release's
    highlights: the sentence names this month's and usually last month's ("increased from 7.75
    per cent in September 2022 to 7.90 per cent in October 2022", "remained unchanged at 8.80
    per cent in February 2024"). Empty when the release has no such sentence."""
    text = _text(content.decode("utf-8", "replace"))
    found = _MCLR.search(text)
    if found is None:
        return {}
    sentence = re.split(r"(?i)Deposit Rates|The share of|WALR", text[found.end() :])[0][:400]
    return {
        date(int(m[3]), _MONTHS.index(m[2]) + 1, 1): float(m[1])
        for m in _PER_CENT_IN.finditer(sentence)
    }


# ----------------------------------------------------------------------- money markets


@dataclass(frozen=True, slots=True)
class MmoSummary:
    as_of: date
    wacr: float | None
    """Call money weighted average rate (per cent)."""
    call_volume: float | None
    """₹ crore."""
    net_liquidity: float | None
    """Net liquidity RBI injected, ₹ crore (absorption negative)."""
    crr_requirement: float | None
    """The banks' average daily CRR requirement for the fortnight, ₹ crore."""


def _number(cell: str) -> float | None:
    """A cell's leading number, ignoring commas and footnote marks ("7.76λ", "20,164.00")."""
    match = re.match(r"^-?[\d,]+(?:\.\d+)?", cell.strip())
    if not match or not re.search(r"\d", match[0]):
        return None
    return float(match[0].replace(",", ""))


def _first_number(cells: Iterable[str]) -> float | None:
    for cell in cells:
        if not re.search(r"\d{2}/\d{2}/\d{4}", cell) and (value := _number(cell)) is not None:
            return value
    return None


_SUB_ITEM = re.compile(r"^\((?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\)\s", re.I)


def parse_mmo_summary(content: bytes) -> MmoSummary:
    """The readings the predictor needs from a Money Market Operations release of any era.

    Where the release prints no net-liquidity row, each LAF leg's amount outstanding (the cell
    before the rate, which ends every operations row) is summed with the MSF and SLF, repos
    positive and reverse repos negative."""
    page = content.decode("utf-8", "replace")
    title = re.search(rf"Money Market Operations as on\s+{_MONTH}\s+(\d{{1,2}}),\s*(\d{{4}})", page)
    if not title:
        raise SourceError("rbi_policy: not a Money Market Operations release")
    as_of = date(int(title[3]), _MONTHS.index(title[1]) + 1, int(title[2]))
    billions = re.search(r"Amount in\s*(?:₹|&#8377;|`|Rs\.?)?\s*billion", page, re.I)
    scale = 100.0 if billions else 1.0
    wacr = volume = net = requirement = None
    legs = 0.0
    section = ""
    sign = 0
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I):
        cells = [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        cells = [c for c in cells if c]
        if not cells:
            continue
        label, lower = cells[0], cells[0].lower()
        if re.match(r"^[A-H]\.\s", label):
            section, sign = lower, 0
        if lower.startswith("i. call money"):
            volume = _first_number(cells[1:2])
            wacr = _first_number(cells[2:3])
            volume = None if volume is None else round(volume * scale, 2)
        elif "net liquidity injected" in lower and (
            "outstanding including" in lower or lower.startswith("f.")
        ):
            value = _number(cells[-1])
            net = None if value is None else round(value * scale, 2)
        elif "cash reserve requirement" in lower:
            value = _number(cells[-1])
            requirement = None if value is None else round(value * scale, 2)
        elif section.startswith("c. liquidity adjustment facility"):
            if _SUB_ITEM.match(label):
                sign = -1 if "reverse repo" in lower else 1 if "repo" in lower else 0
            if sign and len(cells) >= 3 and (amount := _number(cells[-2])) is not None:
                legs += sign * amount
        elif section.startswith("d. marginal standing") and len(cells) >= 3:
            legs += _number(cells[-2]) or 0.0
        elif section.startswith("e. standing liquidity") and lower.startswith("e."):
            legs += _number(cells[-1]) or 0.0
    # Releases from 2020 split today's and outstanding operations and always print the figure;
    # summing their legs this way would not reproduce it, so no sum is taken for them.
    if net is None and legs and "outstanding operations" not in page.lower():
        net = round(legs * scale, 2)
    return MmoSummary(as_of, wacr, volume, net, requirement)


# ----------------------------------------------------------------------- adapter


def _months(first: date, last: date) -> list[tuple[int, int]]:
    out, (y, m) = [], (first.year, first.month)
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class RbiPolicyAdapter:
    source = "rbi_policy"

    def __init__(
        self,
        fetcher: Fetcher,
        specs: tuple[SeriesSpec, ...] = IN_RBI_POLICY_SERIES,
        *,
        pause_s: float = 1.0,
        mmo_before: date = date(2022, 4, 8),
    ) -> None:
        self.fetcher = fetcher
        self.specs = {s.remote: s for s in specs}
        self.pause_s = pause_s
        self.mmo_before = mmo_before
        """Money-market windows are read only where they start before this date; from it the
        daily Money Market Operations series covers them."""

    def _listing(self, first: date, last: date) -> list[Listing]:
        front = self.fetcher.get(self.source, PRESS_URL)
        entries = parse_listing(front.content)
        for year, month in _months(first, last):
            page = archive_month(
                self.fetcher, self.source, front.content, year, month, pause_s=self.pause_s
            )
            entries.extend(parse_listing(page))
        unique = {(e.prid, e.day): e for e in entries if first <= e.day <= last}
        return sorted(unique.values(), key=lambda e: (e.day, e.prid))

    def _page(self, prid: str) -> FetchedBody:
        params = {"prid": prid}
        if (saved := self.fetcher.saved(self.source, PRESS_URL, params)) is not None:
            return saved
        time.sleep(self.pause_s)
        return self.fetcher.get(self.source, PRESS_URL, params)

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        last = end or datetime.now(INDIA).date()
        first = start or last - timedelta(days=60)
        outcome = FetchOutcome()
        listing = self._listing(first, last)
        points: dict[str, list[tuple[date, float]]] = defaultdict(list)
        bodies: list[FetchedBody] = []

        def read(prid: str, what: str) -> bytes | None:
            try:
                body = self._page(prid)
            except SourceError as exc:
                outcome.errors[f"{what} {prid}"] = str(exc)
                return None
            bodies.append(body)
            return body.content

        meetings = merge_meetings(
            parse_schedule(content)
            for entry in listing
            if is_schedule_title(entry.title) and (content := read(entry.prid, "schedule"))
        )
        decisions: dict[date, tuple[Decision, Listing]] = {}
        for entry in listing:
            if entry.day in decisions or not is_decision_title(entry.title):
                continue
            content = read(entry.prid, "decision")
            if content is not None and (decision := parse_decision(content)) is not None:
                decisions[entry.day] = (decision, entry)
        for day, (decision, entry) in sorted(decisions.items()):
            points["mpc/repo"].append((day, decision.repo))
            scheduled = day in meetings or (
                day < date(2017, 4, 1) and "statement by" not in entry.title.lower()
            )
            points["mpc/scheduled"].append((day, 1.0 if scheduled else 0.0))
        for day in sorted(meetings):
            points["mpc/meeting"].append((day, 1.0))

        bills = [e for e in listing if is_tbill_title(e.title)]
        cutoffs: dict[str, float | None] = {}
        found: dict[date, float] = {}
        for day in [*decisions, last + timedelta(days=1)]:
            # The latest auction before the day that has a 91-day cut-off: RBI sometimes
            # rejects every bid (25 Mar 2026), and then the auction before counts.
            for entry in [e for e in bills if e.day < day][::-1][:3]:
                if entry.prid not in cutoffs:
                    content = read(entry.prid, "tbill")
                    cutoffs[entry.prid] = parse_tbill_cutoff(content) if content else None
                if (yield_ := cutoffs[entry.prid]) is not None:
                    found[entry.day] = yield_
                    break
        points["tbill91/cutoff"].extend(sorted(found.items()))

        mmo = {
            entry.prid: entry
            for entry in listing
            if entry.title.startswith("Money Market Operations as on")
        }
        span = timedelta(days=MMO_WINDOW_DAYS)
        windows = [d for d in decisions if d - span < self.mmo_before]
        for prid, entry in mmo.items():
            as_of = _release_day(entry.title)
            if as_of is None or not any(
                d - span <= as_of < min(d, self.mmo_before) for d in windows
            ):
                continue
            content = read(prid, "mmo")
            if content is None:
                continue
            try:
                summary = parse_mmo_summary(content)
            except SourceError as exc:
                outcome.errors[f"mmo {prid}"] = str(exc)
                continue
            for key, value in (
                ("hist/wacr", summary.wacr),
                ("hist/call_volume", summary.call_volume),
                ("hist/net_liquidity", summary.net_liquidity),
                ("hist/crr_requirement", summary.crr_requirement),
            ):
                if value is not None:
                    points[key].append((summary.as_of, value))
        for entry in listing:
            if not is_wss_title(entry.title) or (content := read(entry.prid, "wss")) is None:
                continue
            try:
                reserves = parse_reserves(content)
            except SourceError as exc:
                outcome.errors[f"wss {entry.prid}"] = str(exc)
                continue
            points["wss/reserves"].append((reserves.as_of, reserves.total))
            points["wss/fca"].append((reserves.as_of, reserves.fca))
            points["wss/gold"].append((reserves.as_of, reserves.gold))
        mclr: dict[date, float] = {}
        for entry in listing:  # in release order, so a later release's figure wins
            if is_lending_rates_title(entry.title) and (content := read(entry.prid, "rates")):
                mclr |= parse_mclr(content)
        points["rates/mclr_1y"].extend(sorted(mclr.items()))
        if not bodies:
            raise SourceError(f"rbi_policy: nothing could be read: {outcome.errors}")
        latest = bodies[-1]
        provenance = Provenance(self.source, latest.url, latest.fetched_at, latest.from_cache)
        for remote, values in points.items():
            spec = self.specs.get(remote)
            if spec and values and (series_ids is None or spec.series_id in series_ids):
                outcome.frames.append(SeriesFrame(spec, tidy(values), provenance))
        return outcome


def _release_day(title: str) -> date | None:
    match = re.search(rf"as on {_MONTH} (\d{{1,2}}), (\d{{4}})", title)
    if not match:
        return None
    return date(int(match[3]), _MONTHS.index(match[1]) + 1, int(match[2]))
