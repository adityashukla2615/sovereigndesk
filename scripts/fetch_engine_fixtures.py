"""Snapshot the official data the engine's anchor tests reproduce (stdlib only).

Writes engine/tests/fixtures/{treasurydirect_auctions,gsw_nss}.json with source URLs and the
retrieval date. The tests read only these files, so they stay offline and deterministic.

    py scripts/fetch_engine_fixtures.py
"""

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "engine" / "tests" / "fixtures"
TD_SEARCH = "https://www.treasurydirect.gov/TA_WS/securities/search"
GSW_CSV = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
HEADERS = {"User-Agent": "SovereignDesk fixture builder (research; contact via GitHub)"}

BILL_FIELDS = (
    *("cusip", "securityTerm", "issueDate", "maturityDate", "daysIssueToMaturity"),
    *("highRate", "investmentRate", "highPrice"),
)
COUPON_FIELDS = (
    *("cusip", "securityType", "securityTerm", "issueDate", "datedDate", "maturityDate"),
    *("interestRate", "highYield", "highPrice", "accruedInterest", "reopening"),
)


def _get(url: str, byte_range: str | None = None) -> bytes:
    headers = dict(HEADERS)
    if byte_range:
        headers["Range"] = f"bytes={byte_range}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - fixed https URLs
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return bytes(response.read())


def _td(kind: str, start: str, end: str) -> tuple[str, list[dict[str, str]]]:
    query = f"format=json&type={kind}&dateFieldName=issueDate&startDate={start}&endDate={end}"
    url = f"{TD_SEARCH}?{query}"
    rows = json.loads(_get(url))
    keep = [
        r for r in rows if r.get("inflationProtected") != "Yes" and r.get("floatingRate") != "Yes"
    ]
    return url, keep


def _date(value: str) -> str:
    return value[:10]


def fetch_treasurydirect() -> dict[str, object]:
    bills: list[dict[str, object]] = []
    coupons: list[dict[str, object]] = []
    urls: list[str] = []
    for start, end in (("2023-10-01", "2023-11-15"), ("2026-09-15", "2026-10-19")):
        url, rows = _td("Bill", start, end)
        urls.append(url)
        for r in rows:
            if r.get("highRate") and r.get("investmentRate") and r.get("highPrice"):
                rec: dict[str, object] = {k: r.get(k) for k in BILL_FIELDS}
                rec["issueDate"], rec["maturityDate"] = (
                    _date(r["issueDate"]),
                    _date(r["maturityDate"]),
                )
                bills.append(rec)
    for kind in ("Note", "Bond"):
        url, rows = _td(kind, "2026-05-01", "2026-10-19")
        urls.append(url)
        for r in rows:
            if r.get("highYield") and r.get("highPrice"):
                rec = {k: r.get(k) for k in COUPON_FIELDS}
                for key in ("issueDate", "datedDate", "maturityDate"):
                    rec[key] = _date(r[key])
                coupons.append(rec)
    return {"sources": urls, "bills": bills, "coupons": coupons}


def _gsw_rows(chunk: bytes, columns: list[str]) -> list[dict[str, str]]:
    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()[1:]  # a byte range starts mid-line
    if not text.endswith("\n"):
        lines = lines[:-1]  # and may end mid-line too
    rows = [line.split(",") for line in lines]
    return [dict(zip(columns, r, strict=True)) for r in rows if len(r) == len(columns)]


def fetch_gsw() -> dict[str, object]:
    head = _get(GSW_CSV, "0-12000").decode("utf-8", errors="replace").splitlines()
    columns = next(line for line in head if line.startswith("Date,")).split(",")
    middle = _gsw_rows(_get(GSW_CSV, "9000000-9030000"), columns)
    tail = _gsw_rows(_get(GSW_CSV, "-30000"), columns)
    picked = [middle[0], tail[-1]]
    wanted = ("Date", "BETA0", "BETA1", "BETA2", "BETA3", "TAU1", "TAU2")
    out = []
    for row in picked:
        rec: dict[str, object] = {k: row[k] for k in wanted}
        for prefix in ("SVENY", "SVENF", "SVENPY"):
            rec[prefix] = {str(n): row[f"{prefix}{n:02d}"] for n in range(1, 31)}
        out.append(rec)
    units = "percent; SVENY/SVENF continuous, SVENPY coupon-equivalent"
    return {"sources": [GSW_CSV], "units": units, "rows": out}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(UTC).date().isoformat()
    for name, payload in (
        ("treasurydirect_auctions", fetch_treasurydirect()),
        ("gsw_nss", fetch_gsw()),
    ):
        payload = {"retrieved": retrieved, **payload}
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(OUT.parents[2])}")


if __name__ == "__main__":
    main()
