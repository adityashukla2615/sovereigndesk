"""NSDL: daily foreign portfolio investment (FPI) flows by asset class.

The monthly report lists, for each reporting date, gross purchases, gross sales and net
investment (₹ crore and US$ million) for each asset class, with a row per investment route, a
sub-total per class and a total per date. Negative numbers are printed in parentheses. The
classes changed over the years: equity and debt until 2019; then the voluntary retention route
(Debt-VRR, from March 2019), hybrid, the fully accessible route (Debt-FAR, from April 2020),
mutual funds and AIFs, the original debt class becoming "Debt-General Limit".

The current month comes from the monthly report, earlier months from NSDL's archive (an ASP.NET
form whose "To Date" lists that month's days up to the date). A month's archive saved a few
days after the month ended is final, so it is parsed again rather than posted again.
"""

import html
import re
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from app.data.catalog import IN_NSDL_SERIES, SeriesSpec
from app.data.http import FetchedBody, Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy
from app.data.sources.rbi import INDIA

MONTHLY_URL = "https://www.fpi.nsdl.co.in/web/Reports/Monthly.aspx"
ARCHIVE_URL = "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"
SETTLED_DAYS = 3
"""Days after a month's end from which its archive is final (trades are reported the next
business day)."""

_CLASSES = {
    "Equity": "equity",
    "Debt": "debt_general",  # the only debt class until the VRR arrived in 2019
    "Debt-General Limit": "debt_general",
    "Debt-VRR": "debt_vrr",
    "Debt-FAR": "debt_far",
    "Hybrid": "hybrid",
    "Mutual Funds": "mutual_funds",
    "AIFs": "aifs",
}
_HIDDEN = re.compile(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"')


def _cells(row: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
        for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
    ]


def _amount(cell: str) -> float | None:
    text = cell.replace(",", "").strip()
    negative = text.startswith("(") and text.endswith(")")
    try:
        value = float(text.strip("()"))
    except ValueError:
        return None
    return -value if negative else value


def parse_monthly(content: bytes) -> dict[str, list[tuple[date, float]]]:
    """Net investment per class and in total: keys like ``equity_inr`` and ``total_usd``.

    A class row names the class and its first route ("Equity | Stock Exchange | …"); the
    class's "Sub-total" row carries its net investment. A class not listed above is skipped
    (its sub-total is not attributed to another), but it still counts in the date's total.
    """
    page = content.decode("utf-8", errors="replace")
    out: dict[str, list[tuple[date, float]]] = defaultdict(list)
    day: date | None = None
    current: str | None = None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = _cells(row)
        if not cells:
            continue
        if "Derivative Products" in cells:
            break  # the archive's second table: FPI derivatives, not investment
        if cells[0].startswith("Total for"):
            day = None  # "Total for January", "Total for 2015": sums, not a reporting date
            continue
        if re.fullmatch(r"\d{2}-[A-Z][a-z]{2}-\d{4}", cells[0]):
            day = datetime.strptime(cells[0], "%d-%b-%Y").replace(tzinfo=UTC).date()
            cells = cells[1:]
        if day is None or not cells:
            continue
        if cells[0] in ("Sub-total", "Total") and len(cells) >= 5:
            key = "total" if cells[0] == "Total" else current
            inr, usd = _amount(cells[3]), _amount(cells[4])
            if key and inr is not None and usd is not None:
                out[f"{key}_inr"].append((day, inr))
                out[f"{key}_usd"].append((day, usd))
        elif len(cells) >= 6 and _amount(cells[1]) is None:  # "<class> | <route> | amounts"
            current = _CLASSES.get(cells[0])
    if not out:
        raise SourceError("nsdl: no daily FPI rows found (layout changed?)")
    debt_days: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for route in ("debt_general", "debt_vrr", "debt_far"):
        for unit, idx in (("inr", 0), ("usd", 1)):
            for d, v in out.get(f"{route}_{unit}", []):
                debt_days[d][idx] += v
    out["debt_inr"] = [(d, round(v[0], 2)) for d, v in sorted(debt_days.items())]
    out["debt_usd"] = [(d, round(v[1], 2)) for d, v in sorted(debt_days.items())]
    return dict(out)


def _month_end(year: int, month: int) -> date:
    return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


class NsdlAdapter:
    source = "nsdl"

    def __init__(
        self,
        fetcher: Fetcher,
        specs: tuple[SeriesSpec, ...] = IN_NSDL_SERIES,
        *,
        pause_s: float = 1.0,
    ) -> None:
        self.fetcher = fetcher
        self.specs = {s.remote: s for s in specs}
        self.pause_s = pause_s
        """Seconds before each archive post, to crawl the archive politely."""
        self._form: dict[str, str] | None = None

    def _archive(self, year: int, month: int) -> FetchedBody:
        """One month's daily flows from the archive, "To Date" the month's last day."""
        end = _month_end(year, month)
        fields = {"hdnDate": end.strftime("%d-%b-%Y")}
        saved = self.fetcher.saved_post(self.source, ARCHIVE_URL, fields)
        settled = end + timedelta(days=SETTLED_DAYS)
        if saved is not None and saved.fetched_at.astimezone(INDIA).date() > settled:
            return saved
        if self._form is None:
            front = self.fetcher.get(self.source, ARCHIVE_URL).content.decode("utf-8", "replace")
            hidden = {k: html.unescape(v) for k, v in _HIDDEN.findall(front)}
            if "__VIEWSTATE" not in hidden:
                raise SourceError("nsdl: the archive page has no ASP.NET form state")
            self._form = {k: v for k, v in hidden.items() if k.startswith("__")}
        time.sleep(self.pause_s)
        form = {
            **self._form,
            "__EVENTTARGET": "btnSubmit1",  # the page's "View Report" postback
            "__EVENTARGUMENT": "",
            **fields,
            "HdnValexceldata": "",
            "hdnFlag": "",
        }
        return self.fetcher.post(self.source, ARCHIVE_URL, form, key_fields=("hdnDate",))

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        """The current month; with ``start``, every earlier month from it through the archive."""
        today = datetime.now(INDIA).date()
        this_month = date(today.year, today.month, 1)
        outcome = FetchOutcome()
        bodies: list[FetchedBody] = []
        merged: dict[str, dict[date, float]] = defaultdict(dict)

        def take(body: FetchedBody, what: str) -> None:
            try:
                flows = parse_monthly(body.content)
            except SourceError as exc:
                outcome.errors[what] = str(exc)
                return
            bodies.append(body)
            for key, values in flows.items():
                merged[key].update(values)

        if start is not None:
            month = date(start.year, start.month, 1)
            while month < min(this_month, end or today):
                try:
                    take(self._archive(month.year, month.month), f"archive {month:%Y-%m}")
                except SourceError as exc:
                    outcome.errors[f"archive {month:%Y-%m}"] = str(exc)
                month = _month_end(month.year, month.month) + timedelta(days=1)
        if end is None or end >= this_month:
            take(self.fetcher.get(self.source, MONTHLY_URL), "monthly")
        if not bodies:
            raise SourceError(f"nsdl: nothing could be read: {outcome.errors}")
        latest = bodies[-1]
        provenance = Provenance(self.source, latest.url, latest.fetched_at, latest.from_cache)
        for remote, by_day in merged.items():
            spec = self.specs.get(remote)
            values = [
                (d, v)
                for d, v in sorted(by_day.items())
                if (start is None or d >= start) and (end is None or d <= end)
            ]
            if spec and values and (series_ids is None or spec.series_id in series_ids):
                outcome.frames.append(SeriesFrame(spec, tidy(values), provenance))
        return outcome
