"""Financial Benchmarks India (FBIL): T-bill benchmark curve, overnight MIBOR, FX reference rate.

FBIL's public site is an Angular app that reads these anonymously from ``/wasdm/<product>/
fetchfiltered`` with ``authenticated=false`` (no login or CAPTCHA is involved for published
benchmarks). Requests are split into monthly windows for long histories.
"""

import json
import re
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from app.data.catalog import IN_FBIL_SERIES, SeriesSpec
from app.data.http import Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy

BASE_URL = "https://www.fbil.org.in/wasdm"


def tbill_tenor(name: str) -> str | None:
    """FBIL tenor names → labels: "7 Days" → 7D, "1 Month" → 1M, "12 Months" → 12M."""
    match = re.fullmatch(r"(\d+)\s+(Day|Days|Month|Months)", name.strip())
    if not match:
        return None
    return f"{match[1]}{'D' if match[2].startswith('Day') else 'M'}"


def _day(stamp: str) -> date:
    return datetime.strptime(stamp[:10], "%Y-%m-%d").replace(tzinfo=UTC).date()


def parse_tbill(content: bytes) -> dict[str, list[tuple[date, float]]]:
    out: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in json.loads(content):
        tenor = tbill_tenor(row.get("tenorName", ""))
        if tenor and row.get("rate") is not None:
            out[tenor].append((_day(row["processRunDate"]), float(row["rate"])))
    return dict(out)


def parse_mibor(content: bytes) -> list[tuple[date, float]]:
    """Overnight MIBOR. Over a holiday or weekend FBIL labels the fixing by its term (e.g. 4D);
    it is still the overnight benchmark for that date."""
    return [
        (_day(r["processRunDate"]), float(r["rate"]))
        for r in json.loads(content)
        if r.get("rate") is not None
    ]


def parse_reference_usd(content: bytes) -> list[tuple[date, float]]:
    return [
        (_day(r["processRunDate"]), float(r["rate"]))
        for r in json.loads(content)
        if r.get("subProdName", "").replace(" ", "") == "INR/1USD" and r.get("rate") is not None
    ]


def _windows(start: date, end: date) -> list[tuple[date, date]]:
    out, cursor = [], start
    while cursor <= end:
        stop = min(cursor + timedelta(days=30), end)
        out.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return out


class FbilAdapter:
    source = "fbil"

    def __init__(
        self,
        fetcher: Fetcher,
        specs: tuple[SeriesSpec, ...] = IN_FBIL_SERIES,
        *,
        pause_s: float = 0.5,
    ) -> None:
        self.fetcher = fetcher
        self.specs = {s.remote: s for s in specs}
        self.pause_s = pause_s
        """Seconds before each request, so a long history is fetched politely."""

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        today = datetime.now(UTC).date()
        last = end or today
        first = start or last - timedelta(days=14)
        points: dict[str, list[tuple[date, float]]] = defaultdict(list)
        provenance: Provenance | None = None
        outcome = FetchOutcome()
        for lo, hi in _windows(first, last):
            params = {
                "fromDate": lo.isoformat(),
                "toDate": hi.isoformat(),
                "authenticated": "false",
            }
            for product, parse in (
                ("tbill", parse_tbill),
                ("ovnmibor", parse_mibor),
                ("refrates", parse_reference_usd),
            ):
                time.sleep(self.pause_s)
                try:
                    body = self.fetcher.get(
                        self.source, f"{BASE_URL}/{product}/fetchfiltered", params
                    )
                    parsed = parse(body.content)
                except (SourceError, ValueError, KeyError) as exc:
                    outcome.errors[f"{product} {lo}"] = str(exc)
                    continue
                provenance = Provenance(self.source, body.url, body.fetched_at, body.from_cache)
                if isinstance(parsed, dict):
                    for tenor, values in parsed.items():
                        points[f"tbill/{tenor}"].extend(values)
                else:
                    points["mibor/ON" if product == "ovnmibor" else "usdinr"].extend(parsed)
        if provenance is None:
            raise SourceError(f"fbil: nothing could be fetched: {outcome.errors}")
        for remote, values in points.items():
            spec = self.specs.get(remote)
            if spec and (series_ids is None or spec.series_id in series_ids):
                outcome.frames.append(SeriesFrame(spec, tidy(values), provenance))
        return outcome
