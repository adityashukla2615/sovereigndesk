"""MoSPI (Ministry of Statistics and Programme Implementation): CPI and quarterly GDP.

Read through MoSPI's eSankhyiki MCP server (mcp.mospi.gov.in), which eSankhyiki's ``llms.txt``
and agentic-resource manifest name as the machine-access route to its statistics; its tools
wrap api.mospi.gov.in, which gives anonymous callers ten records a request.

* CPI, All India, combined (rural + urban):
  - base 2012 (Jan 2011 to Dec 2025): the general index and its six groups (food and
    beverages; pan, tobacco and intoxicants; clothing and footwear; housing; fuel and light;
    miscellaneous), and MoSPI's year-on-year inflation for the general index;
  - base 2024 (from Jan 2025; the new series replaced the old with the January 2026 release):
    the general index, its COICOP 2018 divisions, the four groups of division 04 (housing,
    water, electricity, gas and other fuels), and MoSPI's inflation for the general index.
* GDP at constant prices, quarterly: the level (₹ crore) and MoSPI's year-on-year growth, on
  base 2011-12 and base 2022-23.

Monthly values are dated the first of the month and quarterly ones the first day of the quarter
(financial-year Q1 is April-June). Publication lags are the consumers' business.
"""

import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any

from app.data.catalog import IN_MOSPI_SERIES, SeriesSpec
from app.data.http import FetchedBody, Fetcher
from app.data.mcp import McpClient
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy

MCP_URL = "https://mcp.mospi.gov.in/"
CPI_2012_LAST_YEAR = 2025
CPI_2024_FIRST = date(2025, 1, 1)
NAS_BASES = {"2011": "2011-12", "2022": "2022-23"}
NAS_FIRST_YEAR = {"2011": 2011, "2022": 2022}
NAS_INDICATORS = {"real": 5, "real_growth": 22}
MONTHS = {
    name: i + 1
    for i, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December")
    )
}  # fmt: skip
CPI_2012_GROUPS = {
    "General": "general",
    "Food and Beverages": "food_beverages",
    "Pan, Tobacco and Intoxicants": "pan_tobacco",
    "Clothing and Footwear": "clothing_footwear",
    "Housing": "housing",
    "Fuel and Light": "fuel_light",
    "Miscellaneous": "miscellaneous",
}
CPI_2012_SUBGROUPS = "0.99,1.99,2.99,3.99,4.99,5.99,6.99"
"""The "-Overall" subgroup of the general index and of each group."""
CPI_2024_DIVISIONS = ",".join(str(code) for code in range(13))
CPI_2024_GROUPS = ("04.1", "04.3", "04.4", "04.5")
"""Division 04's groups: rentals, maintenance, water supply, electricity, gas and other fuels."""


def _float(value: object) -> float | None:
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN-safe


def _rows(structured: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(structured.get("error"), str):
        raise SourceError(f"mospi: {structured['error'][:300]}")
    rows = structured.get("data")
    if not isinstance(rows, list):
        raise SourceError("mospi: the reply holds no data rows")
    return [r for r in rows if isinstance(r, dict)]


def parse_cpi_2012(rows: Iterable[dict[str, Any]]) -> dict[str, list[tuple[date, float]]]:
    """Base-2012 rows → {remote key: [(month, value)]}: group indices and general inflation."""
    out: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in rows:
        key = CPI_2012_GROUPS.get(str(row.get("group", "")))
        month = MONTHS.get(str(row.get("month", "")))
        if key is None or month is None or not str(row.get("subgroup", "")).endswith("Overall"):
            continue
        when = date(int(row["year"]), month, 1)
        if (index := _float(row.get("index"))) is not None:
            out[f"cpi2012:{key}"].append((when, index))
        if key == "general" and (inflation := _float(row.get("inflation"))) is not None:
            out["cpi2012:general_yoy"].append((when, inflation))
    return dict(out)


def _cpi_2024_code(row: dict[str, Any]) -> str | None:
    """``00`` for the general index, a division (``01``) or one of division 04's groups."""
    if row.get("class") or row.get("sub_class") or row.get("item"):
        return None
    code = row.get("code")
    if code is None:
        return "00" if str(row.get("division", "")).startswith("CPI (General)") else None
    code = str(code)
    if row.get("group") is None and len(code) == 2:
        return code
    return code if code in CPI_2024_GROUPS else None


def parse_cpi_2024(rows: Iterable[dict[str, Any]]) -> dict[str, list[tuple[date, float]]]:
    """Base-2024 rows → {remote key: [(month, value)]} for the general index, the divisions and
    division 04's groups, and general inflation."""
    out: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in rows:
        code = _cpi_2024_code(row)
        month = MONTHS.get(str(row.get("month", "")))
        if code is None or month is None:
            continue
        when = date(int(row["year"]), month, 1)
        if (index := _float(row.get("index"))) is not None:
            out[f"cpi2024:{code}"].append((when, index))
        if code == "00" and (inflation := _float(row.get("inflation"))) is not None:
            out["cpi2024:general_yoy"].append((when, inflation))
    return dict(out)


def quarter_start(fiscal_year: str, quarter: str) -> date:
    """ "2020-21", "Q1" → 1 Apr 2020; Q4 is January-March of the following calendar year."""
    first = int(fiscal_year[:4])
    q = int(quarter.strip().upper().removeprefix("Q"))
    if not 1 <= q <= 4:
        raise ValueError(f"no quarter {quarter!r}")
    return date(first + 1, 1, 1) if q == 4 else date(first, 1 + 3 * q, 1)


def parse_nas(rows: Iterable[dict[str, Any]]) -> list[tuple[date, float]]:
    """Quarterly NAS rows → [(quarter start, constant-price value)]."""
    out = []
    for row in rows:
        if str(row.get("frequency", "Quarterly")) != "Quarterly":
            continue
        value = _float(row.get("constant_price"))
        if value is None:
            continue
        try:
            out.append((quarter_start(str(row["year"]), str(row["quarter"])), value))
        except (KeyError, ValueError):
            continue
    return out


Keep = Callable[[FetchedBody, dict[str, list[tuple[date, float]]]], None]


def fiscal_year(year: int) -> str:
    return f"{year}-{(year + 1) % 100:02d}"


class MospiAdapter:
    source = "mospi"

    def __init__(
        self,
        fetcher: Fetcher,
        specs: tuple[SeriesSpec, ...] = IN_MOSPI_SERIES,
        *,
        pause_s: float = 1.0,
        url: str = MCP_URL,
    ) -> None:
        self.mcp = McpClient(fetcher, self.source, url)
        self.specs = {s.remote: s for s in specs}
        self.pause_s = pause_s
        """Seconds between calls: the server forwards each one to MoSPI's API."""

    def _call(self, arguments: dict[str, Any]) -> tuple[FetchedBody, list[dict[str, Any]]]:
        time.sleep(self.pause_s)
        body, structured = self.mcp.call("get_data", arguments)
        return body, _rows(structured)

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        today = datetime.now(UTC).date()
        last = end or today
        first = start or date(last.year - 1, 1, 1)
        points: dict[str, list[tuple[date, float]]] = defaultdict(list)
        outcome = FetchOutcome()
        bodies: list[FetchedBody] = []

        def keep(body: FetchedBody, parsed: dict[str, list[tuple[date, float]]]) -> None:
            bodies.append(body)
            for remote, values in parsed.items():
                points[remote].extend(values)

        for year in range(max(first.year, 2011), min(last.year, CPI_2012_LAST_YEAR) + 1):
            filters = {
                "base_year": "2012", "series": "Current", "year": str(year), "state_code": "99",
                "sector_code": "3", "subgroup_code": CPI_2012_SUBGROUPS, "limit": "100",
            }  # fmt: skip
            try:
                body, rows = self._call({"dataset": "CPI", "filters": filters})
                keep(body, parse_cpi_2012(rows))
            except SourceError as exc:
                outcome.errors[f"cpi2012 {year}"] = str(exc)
        self._cpi_2024(max(first, CPI_2024_FIRST), last, keep, outcome)
        for base, base_year in NAS_BASES.items():
            years = [
                fiscal_year(y)
                for y in range(max(first.year - 1, NAS_FIRST_YEAR[base]), last.year + 1)
            ]
            for name, indicator in NAS_INDICATORS.items():
                for chunk in (years[i : i + 6] for i in range(0, len(years), 6)):
                    filters = {
                        "base_year": base_year, "series": "Current", "frequency_code": "Quarterly",
                        "indicator_code": str(indicator), "year": ",".join(chunk), "limit": "100",
                    }  # fmt: skip
                    try:
                        body, rows = self._call({"dataset": "NAS", "filters": filters})
                    except SourceError as exc:
                        outcome.errors[f"gdp{base} {name} {chunk[0]}"] = str(exc)
                        continue
                    keep(body, {f"gdp{base}:{name}": parse_nas(rows)})
        if not bodies:
            raise SourceError(f"mospi: nothing could be fetched: {outcome.errors}")
        latest = bodies[-1]
        provenance = Provenance(self.source, latest.url, latest.fetched_at, latest.from_cache)
        for remote, values in points.items():
            spec = self.specs.get(remote)
            if spec and values and (series_ids is None or spec.series_id in series_ids):
                outcome.frames.append(SeriesFrame(spec, tidy(values), provenance))
        return outcome

    def _cpi_2024(self, first: date, last: date, keep: Keep, outcome: FetchOutcome) -> None:
        """One month at a time: the API returns every level of the hierarchy (about 670 rows a
        month, 100 at most per page), divisions first and then groups in code order, so a short
        page or two holds everything needed."""
        wanted = {"00", *(f"{d:02d}" for d in range(1, 14) if d != 12), *CPI_2024_GROUPS}
        month = date(first.year, first.month, 1)
        while month <= last:
            found: dict[str, list[tuple[date, float]]] = {}
            for page in (1, 2, 3):
                filters = {
                    "base_year": "2024", "series": "Current", "year": str(month.year),
                    "month_code": str(month.month), "state_code": "1", "sector_code": "3",
                    "division_code": CPI_2024_DIVISIONS, "limit": "40", "page": str(page),
                }  # fmt: skip
                try:
                    body, rows = self._call({"dataset": "CPI", "filters": filters})
                except SourceError as exc:
                    outcome.errors[f"cpi2024 {month:%Y-%m} p{page}"] = str(exc)
                    break
                if not rows:
                    break
                parsed = parse_cpi_2024(rows)
                found.update(parsed)
                keep(body, parsed)
                codes = {k.split(":")[1] for k in found if not k.endswith("_yoy")}
                if wanted <= codes:
                    break
            if not found:
                return  # not published yet
            month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
