"""US Treasury daily par yield curve (CSV, one file per year)."""

import csv
import io
from collections import defaultdict
from datetime import UTC, date, datetime

from app.data.catalog import TREASURY_SERIES, SeriesSpec
from app.data.http import Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy

CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
)


def parse_par_curve_csv(content: bytes) -> dict[str, list[tuple[date, float]]]:
    """Columns are matched by header name, because tenors were added over the years
    (2-month in 2018, 4-month in 2022, 6-week in 2025). Blank cells are missing values."""
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    if not reader.fieldnames or reader.fieldnames[0] != "Date":
        raise SourceError("treasury: CSV does not start with a Date column")
    columns: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in reader:
        day = datetime.strptime(row["Date"], "%m/%d/%Y").replace(tzinfo=UTC).date()
        for column, cell in row.items():
            if column != "Date" and cell not in (None, "", "N/A"):
                columns[column].append((day, float(cell)))
    return dict(columns)


class TreasuryCurveAdapter:
    source = "treasury"

    def __init__(self, fetcher: Fetcher, specs: tuple[SeriesSpec, ...] = TREASURY_SERIES) -> None:
        self.fetcher = fetcher
        self.specs = specs

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        today = datetime.now(UTC).date()
        first, last = (start or today).year, (end or today).year
        points: dict[str, list[tuple[date, float]]] = defaultdict(list)
        provenance: Provenance | None = None
        outcome = FetchOutcome()
        for year in range(first, last + 1):
            params = {
                "type": "daily_treasury_yield_curve",
                "field_tdr_date_value": str(year),
                "_format": "csv",
            }
            try:
                body = self.fetcher.get(self.source, CSV_URL.format(year=year), params)
                parsed = parse_par_curve_csv(body.content)
            except (SourceError, ValueError) as exc:
                outcome.errors[f"year {year}"] = str(exc)
                continue
            provenance = Provenance(self.source, body.url, body.fetched_at, body.from_cache)
            for column, values in parsed.items():
                points[column].extend(values)
        if provenance is None:
            raise SourceError(f"treasury: no year could be fetched: {outcome.errors}")
        for spec in self.specs:
            if series_ids is not None and spec.series_id not in series_ids:
                continue
            values = [
                (d, v)
                for d, v in points.get(spec.remote, [])
                if (start is None or d >= start) and (end is None or d <= end)
            ]
            if values:
                outcome.frames.append(SeriesFrame(spec, tidy(values), provenance))
        return outcome
