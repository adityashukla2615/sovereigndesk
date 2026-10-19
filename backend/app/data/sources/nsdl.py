"""NSDL: daily foreign portfolio investment (FPI) flows by asset class, current month.

The monthly report lists, for each reporting date, gross purchases, gross sales and net
investment (₹ crore and US$ million) for equity, three debt routes (general limit, VRR, FAR),
hybrid, mutual funds and AIFs, with a sub-total per class and a total per date. Negative
numbers are printed in parentheses. Earlier months come from NSDL's archive (Phase 9).
"""

import html
import re
from collections import defaultdict
from datetime import UTC, date, datetime

from app.data.catalog import IN_NSDL_SERIES, SeriesSpec
from app.data.http import Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy

MONTHLY_URL = "https://www.fpi.nsdl.co.in/web/Reports/Monthly.aspx"

_CLASSES = {
    "Equity": "equity",
    "Debt-General Limit": "debt_general",
    "Debt-VRR": "debt_vrr",
    "Debt-FAR": "debt_far",
    "Hybrid": "hybrid",
    "Mutual Funds": "mutual_funds",
    "AIFs": "aifs",
}


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
    """Net investment per class and in total: keys like ``equity_inr`` and ``total_usd``."""
    page = content.decode("utf-8", errors="replace")
    out: dict[str, list[tuple[date, float]]] = defaultdict(list)
    day: date | None = None
    current: str | None = None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = _cells(row)
        if not cells:
            continue
        if re.fullmatch(r"\d{2}-[A-Z][a-z]{2}-\d{4}", cells[0]):
            day = datetime.strptime(cells[0], "%d-%b-%Y").replace(tzinfo=UTC).date()
            cells = cells[1:]
        if day is None or not cells:
            continue
        if cells[0] in _CLASSES:
            current = _CLASSES[cells[0]]
        elif cells[0] in ("Sub-total", "Total") and len(cells) >= 5:
            key = "total" if cells[0] == "Total" else current
            inr, usd = _amount(cells[3]), _amount(cells[4])
            if key and inr is not None and usd is not None:
                out[f"{key}_inr"].append((day, inr))
                out[f"{key}_usd"].append((day, usd))
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


class NsdlAdapter:
    source = "nsdl"

    def __init__(self, fetcher: Fetcher, specs: tuple[SeriesSpec, ...] = IN_NSDL_SERIES) -> None:
        self.fetcher = fetcher
        self.specs = {s.remote: s for s in specs}

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        body = self.fetcher.get(self.source, MONTHLY_URL)
        provenance = Provenance(self.source, body.url, body.fetched_at, body.from_cache)
        outcome = FetchOutcome()
        for remote, values in parse_monthly(body.content).items():
            spec = self.specs.get(remote)
            if spec and (series_ids is None or spec.series_id in series_ids):
                outcome.frames.append(SeriesFrame(spec, tidy(values), provenance))
        return outcome
