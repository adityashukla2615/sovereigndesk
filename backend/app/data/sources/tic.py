"""Treasury International Capital (TIC): major foreign holders of Treasury securities.

``slt_table5.txt`` has the latest 13 months; ``mfhhis01.txt`` stacks one block per year back
to 2000. Both are tab-separated, in USD billions, holdings at the end of each month. Where they
overlap the current table wins, since it carries the latest revisions. (The older ``mfh.txt``
stopped updating in January 2023.)
"""

import calendar
import re
from collections import defaultdict
from datetime import date

from app.data.catalog import tic_spec
from app.data.http import Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy

DOCS = "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents"
CURRENT_URL = f"{DOCS}/slt_table5.txt"
HISTORY_URL = f"{DOCS}/mfhhis01.txt"

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
_FOOTNOTE = re.compile(r"\s+\d+/\s*$")

Holdings = dict[str, dict[date, float]]


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _label(cell: str) -> str:
    return _FOOTNOTE.sub("", cell.strip().strip('"').strip())


def _number(cell: str) -> float | None:
    try:
        return float(cell.strip().replace(",", ""))
    except ValueError:
        return None


def _lines(content: bytes) -> list[list[str]]:
    return [line.split("\t") for line in content.decode("utf-8-sig", errors="replace").splitlines()]


def _read_rows(rows: list[list[str]], start: int, dates: list[date | None], into: Holdings) -> None:
    for cells in rows[start:]:
        label = _label(cells[0]) if cells else ""
        if not label or label.lower().startswith(("notes", "country")):
            return
        for when, cell in zip(dates, cells[1:], strict=False):
            value = _number(cell)
            if when is not None and value is not None:
                into[label][when] = value


def parse_current(content: bytes) -> Holdings:
    rows = _lines(content)
    header = next((i for i, cells in enumerate(rows) if _label(cells[0]) == "Country"), None)
    if header is None:
        raise SourceError("tic: slt_table5 has no Country header")
    dates: list[date | None] = []
    for cell in rows[header][1:]:
        match = re.fullmatch(r"\s*(\d{4})-(\d{2})\s*", cell)
        dates.append(_month_end(int(match[1]), int(match[2])) if match else None)
    holdings: Holdings = defaultdict(dict)
    _read_rows(rows, header + 1, dates, holdings)
    return dict(holdings)


def parse_history(content: bytes) -> Holdings:
    rows = _lines(content)
    holdings: Holdings = defaultdict(dict)
    for i, cells in enumerate(rows):
        if _label(cells[0]) != "Country" or i == 0:
            continue
        months, years = rows[i - 1][1:], cells[1:]
        dates: list[date | None] = []
        for month, year in zip(months, years, strict=False):
            m, y = _MONTHS.get(month.strip().lower()[:3]), year.strip()
            dates.append(_month_end(int(y), m) if m and y.isdigit() else None)
        first = i + 2 if i + 1 < len(rows) and rows[i + 1][1:2] and "--" in rows[i + 1][1] else i + 1
        _read_rows(rows, first, dates, holdings)
    if not holdings:
        raise SourceError("tic: mfhhis01 has no Country blocks")
    return dict(holdings)


class TicAdapter:
    source = "tic"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        outcome = FetchOutcome()
        merged: Holdings = defaultdict(dict)
        provenance: Provenance | None = None
        for url, parse in ((HISTORY_URL, parse_history), (CURRENT_URL, parse_current)):
            try:
                body = self.fetcher.get(self.source, url)
                for label, values in parse(body.content).items():
                    merged[label].update(values)  # current table last, so it wins
                provenance = Provenance(self.source, body.url, body.fetched_at, body.from_cache)
            except (SourceError, ValueError) as exc:
                outcome.errors[url.rsplit("/", 1)[-1]] = str(exc)
        if provenance is None:
            raise SourceError(f"tic: nothing could be fetched: {outcome.errors}")
        for label, values in merged.items():
            spec = tic_spec(label)
            if series_ids is not None and spec.series_id not in series_ids:
                continue
            points = [
                (d, v)
                for d, v in values.items()
                if (start is None or d >= start) and (end is None or d <= end)
            ]
            if points:
                outcome.frames.append(SeriesFrame(spec, tidy(points), provenance))
        return outcome
