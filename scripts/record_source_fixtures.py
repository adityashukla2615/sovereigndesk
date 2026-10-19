"""Record small real responses from each data source for the backend's offline adapter tests.

    py scripts/record_source_fixtures.py

Writes backend/tests/fixtures/sources/. Responses are trimmed (date filters, small pages) but
otherwise verbatim; the FRED key is sent as a query parameter and FRED never echoes it, and
the files are checked for it before they are written.
"""

import urllib.parse
import urllib.request
from pathlib import Path

from app.config import Settings

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "sources"
FISCAL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
TIC = "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents"
TREASURY = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={year}&_format=csv"
)
HEADERS = {"User-Agent": "SovereignDesk fixture recorder"}


def get(url: str, params: dict[str, str] | None = None) -> bytes:
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    request = urllib.request.Request(full, headers=HEADERS)  # noqa: S310 - fixed https URLs
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return bytes(response.read())


def fiscal(endpoint: str, **params: str) -> bytes:
    return get(FISCAL + endpoint, params)


def main() -> None:
    settings = Settings()
    if settings.fred_api_key is None:
        raise SystemExit("FRED_API_KEY is needed to record the FRED fixture")
    key = settings.fred_api_key.get_secret_value()
    files: dict[str, bytes] = {
        # 12 Oct 2026 (Columbus Day) is a bond-market holiday: FRED reports ".".
        "fred_dgs10.json": get(
            "https://api.stlouisfed.org/fred/series/observations",
            {
                "series_id": "DGS10",
                "api_key": key,
                "file_type": "json",
                "observation_start": "2026-10-05",
                "observation_end": "2026-10-15",
            },
        ),
        "treasury_2026.csv": b"\n".join(get(TREASURY.format(year=2026)).splitlines()[:6]) + b"\n",
        "treasury_2017.csv": b"\n".join(get(TREASURY.format(year=2017)).splitlines()[:4]) + b"\n",
        "debt_to_penny_p1.json": fiscal(
            "/v2/accounting/od/debt_to_penny",
            **{
                "fields": "record_date,tot_pub_debt_out_amt,debt_held_public_amt,intragov_hold_amt",
                "filter": "record_date:gte:2026-10-08,record_date:lte:2026-10-13",
                "sort": "record_date",
                "page[size]": "2",
                "page[number]": "1",
            },
        ),
        "debt_to_penny_p2.json": fiscal(
            "/v2/accounting/od/debt_to_penny",
            **{
                "fields": "record_date,tot_pub_debt_out_amt,debt_held_public_amt,intragov_hold_amt",
                "filter": "record_date:gte:2026-10-08,record_date:lte:2026-10-13",
                "sort": "record_date",
                "page[size]": "2",
                "page[number]": "2",
            },
        ),
        "avg_interest_rates.json": fiscal(
            "/v2/accounting/od/avg_interest_rates",
            **{
                "fields": "record_date,security_type_desc,security_desc,avg_interest_rate_amt",
                "filter": "record_date:eq:2026-09-30",
                "page[size]": "100",
            },
        ),
        "interest_expense.json": fiscal(
            "/v2/accounting/od/interest_expense",
            **{
                "fields": "record_date,expense_catg_desc,month_expense_amt",
                "filter": "record_date:eq:2026-09-30",
                "page[size]": "100",
            },
        ),
        "mspd_latest.json": fiscal(
            "/v1/debt/mspd/mspd_table_3_market",
            **{"fields": "record_date", "sort": "-record_date", "page[size]": "1"},
        ),
        "mspd_rows.json": fiscal(
            "/v1/debt/mspd/mspd_table_3_market",
            **{
                "fields": "record_date,security_class1_desc,security_class2_desc,interest_rate_pct,"
                "yield_pct,issue_date,maturity_date,issued_amt,outstanding_amt",
                "filter": "record_date:eq:2026-09-30",
                "page[size]": "6",
            },
        ),
        "tic_slt_table5.txt": get(f"{TIC}/slt_table5.txt"),
        # First two yearly blocks plus the start of the footnotes.
        "tic_mfhhis01.txt": b"\n".join(get(f"{TIC}/mfhhis01.txt").splitlines()[:105]) + b"\n",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        if key.encode() in content:
            raise SystemExit(f"{name} contains the API key; refusing to write it")
        (OUT / name).write_bytes(content)
        print(f"wrote {name} ({len(content):,} bytes)")


if __name__ == "__main__":
    main()
