"""FBIL's daily G-sec valuation: the par-yield curve from the published Excel workbooks.

FBIL publishes one workbook per business day ("FBIL GOI Prices including Par Yield, Special and
Note on FRB and IIB"), downloadable anonymously from ``/wasdm/gsec/downloadPublished?date=``;
``/wasdm/gsec/fetchfiltered`` lists the dates published in a window. The "Par Yield" sheet
("Par-Yield" in the legacy .xls files FBIL served until 10 Feb 2023) gives FBIL's base/par
yield curve by tenor in quarter years: semi-annual par yields, the 3-month point a simple
(money-market) yield. A workbook never changes once published, so a copy saved by an earlier
crawl is parsed instead of downloaded again.
"""

import contextlib
import io
import json
import time
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import pandas as pd

from app.data.catalog import FBIL_GSEC_TENORS, IN_FBIL_GSEC_SERIES, SeriesSpec
from app.data.http import FetchedBody, Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy
from app.data.sources.fbil import BASE_URL

LIST_URL = f"{BASE_URL}/gsec/fetchfiltered"
FILE_URL = f"{BASE_URL}/gsec/downloadPublished"
MAX_FILE_BYTES = 5_000_000
"""The legacy .xls workbooks are about 0.75 MB, the .xlsx ones about 25 kB."""
MAX_UNZIPPED_BYTES = 50_000_000
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
"""How a legacy (BIFF) .xls workbook begins."""
_DATE_FORMATS = ("%d-%b-%Y", "%d %b, %Y", "%d-%b-%y", "%d %b %Y")


def published_dates(content: bytes) -> list[date]:
    """The publication dates in a ``fetchfiltered`` listing, ascending."""
    rows = json.loads(content)
    if not isinstance(rows, list):
        raise ValueError("expected a list of publications")
    return sorted({date.fromisoformat(str(r["processRunDate"])[:10]) for r in rows})


def _letters(text: object) -> str:
    return "".join(c for c in str(text).lower() if c.isalpha())


def _sheet_date(frame: pd.DataFrame) -> date | None:
    """The valuation date printed in the sheet's title rows, if one can be read."""
    for value in frame.head(4).to_numpy().ravel():
        if isinstance(value, datetime):
            return value.date()
        text = str(value).strip()
        for fmt in _DATE_FORMATS:
            with contextlib.suppress(ValueError):
                return datetime.strptime(text, fmt).replace(tzinfo=UTC).date()
    return None


def _check_size(content: bytes) -> None:
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"workbook of {len(content):,} bytes is larger than expected")
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            unzipped = sum(info.file_size for info in archive.infolist())
        if unzipped > MAX_UNZIPPED_BYTES:
            raise ValueError(f"workbook unzips to {unzipped:,} bytes, larger than expected")


def parse_par_yields(content: bytes) -> tuple[date | None, dict[float, float]]:
    """(the date printed on the sheet, {tenor in years: par yield in %}) from one workbook.

    The value read is the semi-annual column; the sheet also gives an annualised one."""
    _check_size(content)
    try:
        # Legacy .xls through calamine; .xlsx through openpyxl (XML via defusedxml).
        engine: Literal["calamine", "openpyxl"] = (
            "calamine" if content.startswith(_OLE2) else "openpyxl"
        )
        book = pd.ExcelFile(io.BytesIO(content), engine=engine)
    except Exception as exc:  # an HTML error page, a truncated download, a format change
        raise ValueError(f"not a readable workbook: {type(exc).__name__}: {exc}") from None
    with book:
        names = [str(n) for n in book.sheet_names]
        name = next((n for n in names if _letters(n) == "paryield"), None)
        if name is None:
            raise ValueError(f"no par-yield sheet among {names}")
        try:
            frame = pd.read_excel(book, sheet_name=name, header=None, dtype=object)
        except Exception as exc:
            raise ValueError(f"unreadable par-yield sheet: {type(exc).__name__}: {exc}") from None
    header = next(
        (i for i, v in enumerate(frame.iloc[:, 0]) if _letters(v).startswith("tenor")), None
    )
    if header is None or frame.shape[1] < 2:
        raise ValueError("the par-yield sheet has no tenor column")
    curve: dict[float, float] = {}
    for tenor, value in frame.iloc[header + 1 :, :2].itertuples(index=False):
        try:
            years, rate = float(tenor), float(value)
        except (TypeError, ValueError):
            continue
        if years > 0 and rate == rate:  # NaN-safe
            curve[round(years, 4)] = rate
    if not curve:
        raise ValueError("the par-yield sheet has no rows")
    tenors = list(curve)
    if tenors != sorted(tenors) or not all(0 < r < 30 for r in curve.values()):
        raise ValueError("par yields out of order or outside 0-30%")
    return _sheet_date(frame), curve


def _windows(start: date, end: date) -> list[tuple[date, date]]:
    out, cursor = [], start
    while cursor <= end:
        stop = min(cursor + timedelta(days=30), end)
        out.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return out


class FbilGsecAdapter:
    source = "fbil_gsec"

    def __init__(
        self,
        fetcher: Fetcher,
        specs: tuple[SeriesSpec, ...] = IN_FBIL_GSEC_SERIES,
        *,
        pause_s: float = 1.0,
    ) -> None:
        self.fetcher = fetcher
        self.specs = {s.remote: s for s in specs}
        self.pause_s = pause_s
        """Seconds before each download, so a long history is fetched politely."""

    def published(self, start: date, end: date) -> list[date]:
        days: set[date] = set()
        for lo, hi in _windows(start, end):
            time.sleep(self.pause_s)
            params = {
                "fromDate": lo.isoformat(),
                "toDate": hi.isoformat(),
                "authenticated": "false",
            }
            body = self.fetcher.get(self.source, LIST_URL, params)
            try:
                days.update(published_dates(body.content))
            except (ValueError, KeyError, TypeError) as exc:
                raise SourceError(f"fbil_gsec: unreadable listing for {lo}: {exc}") from None
        return sorted(days)

    def around(self, events: Iterable[date], *, before: int = 1, after: int = 1) -> list[date]:
        """Publication dates around each event: the event day (or the next publication after it)
        plus ``before`` publications before and ``after`` after."""
        out: set[date] = set()
        for event in sorted(set(events)):
            days = self.published(event - timedelta(days=12), event + timedelta(days=12))
            later = [i for i, d in enumerate(days) if d >= event]
            if not later:
                continue
            i = later[0]
            out.update(days[max(0, i - before) : i + after + 1])
        return sorted(out)

    def _workbook(self, day: date) -> tuple[FetchedBody, dict[float, float]]:
        params = {"date": day.isoformat()}
        if (saved := self.fetcher.saved(self.source, FILE_URL, params)) is not None:
            with contextlib.suppress(ValueError):
                return saved, self._checked(day, saved.content)
        time.sleep(self.pause_s)
        body = self.fetcher.get(self.source, FILE_URL, params)
        return body, self._checked(day, body.content)

    @staticmethod
    def _checked(day: date, content: bytes) -> dict[float, float]:
        printed, curve = parse_par_yields(content)
        if printed is not None and printed != day:
            raise ValueError(f"workbook requested for {day} is dated {printed}")
        return curve

    def fetch(
        self,
        series_ids: set[str] | None = None,
        start: date | None = None,
        end: date | None = None,
        *,
        also: Iterable[date] = (),
    ) -> FetchOutcome:
        """Every publication in [start, end] (the last two weeks by default), plus the dates in
        ``also`` (e.g. publications around older repo changes)."""
        last = end or datetime.now(UTC).date()
        first = start or last - timedelta(days=14)
        days = sorted(set(self.published(first, last)) | set(also))
        points: dict[str, list[tuple[date, float]]] = defaultdict(list)
        provenance: Provenance | None = None
        outcome = FetchOutcome()
        for day in days:
            try:
                body, curve = self._workbook(day)
            except (SourceError, ValueError) as exc:
                outcome.errors[f"gsec {day}"] = str(exc)
                continue
            provenance = Provenance(self.source, body.url, body.fetched_at, body.from_cache)
            for label, years in FBIL_GSEC_TENORS.items():
                if (value := curve.get(round(years, 4))) is not None:
                    points[f"par/{label}"].append((day, value))
        if provenance is None:
            raise SourceError(f"fbil_gsec: no workbook could be read: {outcome.errors}")
        for remote, values in points.items():
            spec = self.specs.get(remote)
            if spec and (series_ids is None or spec.series_id in series_ids):
                outcome.frames.append(SeriesFrame(spec, tidy(values), provenance))
        return outcome
