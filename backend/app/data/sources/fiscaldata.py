"""US Treasury FiscalData API: debt to the penny, average interest rates, interest expense,
and the security-level Monthly Statement of the Public Debt (MSPD table 3)."""

import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from app.data.catalog import FISCAL_SERIES, SeriesSpec
from app.data.http import FetchedBody, Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy

BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
DEBT_TO_PENNY = "/v2/accounting/od/debt_to_penny"
AVG_INTEREST_RATES = "/v2/accounting/od/avg_interest_rates"
INTEREST_EXPENSE = "/v2/accounting/od/interest_expense"
MSPD_TABLE_3 = "/v1/debt/mspd/mspd_table_3_market"
PAGE_SIZE = 10_000


def _number(value: str | None) -> float | None:
    return None if value in (None, "", "null") else float(value)


def _date(value: str | None) -> date | None:
    return None if value in (None, "", "null") else date.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class MspdRow:
    record_date: date
    cusip: str
    issue_date: date
    security_class: str
    maturity_date: date
    interest_rate_pct: float | None
    yield_pct: float | None
    issued_musd: float | None
    outstanding_musd: float | None


@dataclass(frozen=True, slots=True)
class MspdSnapshot:
    rows: list[MspdRow]
    provenance: Provenance


class FiscalDataAdapter:
    source = "fiscaldata"

    def __init__(self, fetcher: Fetcher, specs: tuple[SeriesSpec, ...] = FISCAL_SERIES) -> None:
        self.fetcher = fetcher
        self.specs = specs

    def _pages(
        self, endpoint: str, params: dict[str, str]
    ) -> Iterator[tuple[dict[str, str], FetchedBody]]:
        page, pages = 1, 1
        while page <= pages:
            query = {**params, "page[size]": str(PAGE_SIZE), "page[number]": str(page)}
            body = self.fetcher.get(self.source, BASE_URL + endpoint, query)
            payload = json.loads(body.content)
            if "data" not in payload:
                raise SourceError(f"fiscaldata: unexpected response from {endpoint}")
            pages = int(payload.get("meta", {}).get("total-pages", 1))
            for record in payload["data"]:
                yield record, body
            page += 1

    def _query(
        self, endpoint: str, fields: list[str], start: date | None, end: date | None
    ) -> tuple[list[dict[str, str]], Provenance]:
        filters = []
        if start:
            filters.append(f"record_date:gte:{start.isoformat()}")
        if end:
            filters.append(f"record_date:lte:{end.isoformat()}")
        params = {"fields": ",".join(fields), "sort": "record_date"}
        if filters:
            params["filter"] = ",".join(filters)
        records: list[dict[str, str]] = []
        last: FetchedBody | None = None
        for record, body in self._pages(endpoint, params):
            records.append(record)
            last = body
        if last is None:
            raise SourceError(f"fiscaldata: {endpoint} returned no records")
        return records, Provenance(self.source, last.url, last.fetched_at, last.from_cache)

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        wanted = [s for s in self.specs if series_ids is None or s.series_id in series_ids]
        groups: dict[str, list[SeriesSpec]] = defaultdict(list)
        for spec in wanted:
            groups[spec.series_id.split("/")[1]].append(spec)
        outcome = FetchOutcome()
        handlers = {"debt": self._debt, "avg_rate": self._avg_rates, "interest": self._interest}
        for group, specs in groups.items():
            try:
                outcome.frames.extend(handlers[group](specs, start, end))
            except (SourceError, ValueError, KeyError) as exc:
                outcome.errors[group] = str(exc)
        if not outcome.frames and outcome.errors:
            raise SourceError(f"fiscaldata: every dataset failed: {outcome.errors}")
        return outcome

    def _debt(
        self, specs: list[SeriesSpec], start: date | None, end: date | None
    ) -> list[SeriesFrame]:
        fields = ["record_date", *[s.remote for s in specs]]
        records, provenance = self._query(DEBT_TO_PENNY, fields, start, end)
        frames = []
        for spec in specs:
            points = [
                (date.fromisoformat(r["record_date"]), v)
                for r in records
                if (v := _number(r.get(spec.remote))) is not None
            ]
            frames.append(SeriesFrame(spec, tidy(points), provenance))
        return frames

    def _avg_rates(
        self, specs: list[SeriesSpec], start: date | None, end: date | None
    ) -> list[SeriesFrame]:
        fields = ["record_date", "security_type_desc", "security_desc", "avg_interest_rate_amt"]
        records, provenance = self._query(AVG_INTEREST_RATES, fields, start, end)
        frames = []
        for spec in specs:
            points = [
                (date.fromisoformat(r["record_date"]), v)
                for r in records
                if r["security_desc"] == spec.remote
                and r["security_type_desc"] == "Marketable"
                and (v := _number(r.get("avg_interest_rate_amt"))) is not None
            ]
            frames.append(SeriesFrame(spec, tidy(points), provenance))
        return frames

    def _interest(
        self, specs: list[SeriesSpec], start: date | None, end: date | None
    ) -> list[SeriesFrame]:
        fields = ["record_date", "expense_catg_desc", "month_expense_amt"]
        records, provenance = self._query(INTEREST_EXPENSE, fields, start, end)
        frames = []
        for spec in specs:
            totals: dict[date, float] = defaultdict(float)
            for r in records:
                if spec.remote in ("*", r["expense_catg_desc"]):
                    amount = _number(r.get("month_expense_amt"))
                    if amount is not None:
                        totals[date.fromisoformat(r["record_date"])] += amount
            frames.append(SeriesFrame(spec, tidy(sorted(totals.items())), provenance))
        return frames

    def mspd_latest(self) -> MspdSnapshot:
        """Every marketable security outstanding at the latest month-end in MSPD table 3."""
        latest = json.loads(
            self.fetcher.get(
                self.source,
                BASE_URL + MSPD_TABLE_3,
                {"fields": "record_date", "sort": "-record_date", "page[size]": "1"},
            ).content
        )["data"][0]["record_date"]
        fields = [
            "record_date", "security_class1_desc", "security_class2_desc", "interest_rate_pct",
            "yield_pct", "issue_date", "maturity_date", "issued_amt", "outstanding_amt",
        ]  # fmt: skip
        params = {"fields": ",".join(fields), "filter": f"record_date:eq:{latest}"}
        rows: list[MspdRow] = []
        last: FetchedBody | None = None
        for r, body in self._pages(MSPD_TABLE_3, params):
            last = body
            issue, maturity = _date(r["issue_date"]), _date(r["maturity_date"])
            if issue is None or maturity is None or r["security_class2_desc"] in (None, "", "null"):
                continue  # subtotal lines carry no CUSIP or dates
            rows.append(
                MspdRow(
                    record_date=date.fromisoformat(r["record_date"]),
                    cusip=r["security_class2_desc"],
                    issue_date=issue,
                    security_class=r["security_class1_desc"],
                    maturity_date=maturity,
                    interest_rate_pct=_number(r["interest_rate_pct"]),
                    yield_pct=_number(r["yield_pct"]),
                    issued_musd=_number(r["issued_amt"]),
                    outstanding_musd=_number(r["outstanding_amt"]),
                )
            )
        if last is None or not rows:
            raise SourceError("fiscaldata: MSPD table 3 returned no securities")
        return MspdSnapshot(
            rows, Provenance(self.source, last.url, last.fetched_at, last.from_cache)
        )
