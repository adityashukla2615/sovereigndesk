"""Record real responses from the Indian sources for the backend's offline parser tests.

    py scripts/record_india_fixtures.py              # everything
    py scripts/record_india_fixtures.py --only gsec  # just FBIL's G-sec workbooks
    py scripts/record_india_fixtures.py --only mospi # just MoSPI's MCP replies

Writes backend/tests/fixtures/india/ verbatim: the RBI homepage, Money Market Operations
releases from several format eras, one month of the RBI press-release archive, FBIL T-bill and
MIBOR JSON, FBIL's G-sec listing and workbooks (current .xlsx and legacy .xls), NSDL's monthly
FPI page, and MoSPI's MCP replies for CPI (both bases) and GDP. It also writes
engine/tests/fixtures/fbil_curve_2026-10-12.json: FBIL's par and zero-coupon curves for one
day, as published. Requests are spaced politely.
"""

import argparse
import html
import io
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from pathlib import Path

import pandas as pd

from app.data.sources.fbil_gsec import parse_par_yields

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "tests" / "fixtures" / "india"
ENGINE_OUT = ROOT / "engine" / "tests" / "fixtures"
CURVE_DAY = "2026-10-12"
RBI_PR = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
FBIL = "https://www.fbil.org.in/wasdm"
MOSPI_MCP = "https://mcp.mospi.gov.in/"
UA = "Mozilla/5.0 (compatible; SovereignDesk research terminal)"

_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
_opener.addheaders = [("User-Agent", UA)]


def get(url: str, data: bytes | None = None) -> bytes:
    time.sleep(1.0)
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")  # noqa: S310
    with _opener.open(request, timeout=60) as response:
        return bytes(response.read())


def archive_month(year: int, month: int) -> bytes:
    page = get(RBI_PR).decode("utf-8", "replace")
    hidden = dict(
        re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]+" value="([^"]*)"', page)
    )
    form = {k: html.unescape(v) for k, v in hidden.items() if k.startswith("__")}
    form |= {"hdnYear": str(year), "hdnMonth": str(month), "UsrFontCntr$btn": ""}
    return get(RBI_PR, urllib.parse.urlencode(form).encode())


def mmo_prid(listing: bytes, day_title: str) -> str:
    match = re.search(
        rf"prid=(\d+)>Money Market Operations as on {re.escape(day_title)}<",
        listing.decode("utf-8", "replace"),
    )
    if not match:
        raise SystemExit(f"no MMO release titled {day_title!r} in the archive page")
    return match[1]


def _zero_coupon(content: bytes) -> list[list[float]]:
    """FBIL's ZCYC sheet: (tenor in years, semi-annual zero-coupon yield in %)."""
    frame = pd.read_excel(io.BytesIO(content), sheet_name="ZCYC", header=None, dtype=object)
    rows: list[list[float]] = []
    for tenor, value in frame.iloc[:, :2].itertuples(index=False):
        try:
            rows.append([float(tenor), float(value)])
        except (TypeError, ValueError):
            continue
    return rows


def gsec_files() -> dict[str, bytes]:
    window = "fromDate=2026-10-01&toDate=2026-10-16&authenticated=false"
    gsec = get(f"{FBIL}/gsec/downloadPublished?date={CURVE_DAY}")
    strips = get(f"{FBIL}/strips/downloadPublished?date={CURVE_DAY}")
    _, par = parse_par_yields(gsec)
    curve = {
        "retrieved": datetime.now(UTC).date().isoformat(),
        "date": CURVE_DAY,
        "sources": [
            f"{FBIL}/gsec/downloadPublished?date={CURVE_DAY}",
            f"{FBIL}/strips/downloadPublished?date={CURVE_DAY}",
        ],
        "units": "percent, semi-annual compounding; the 0.25-year par point is a simple yield",
        "par": [[tenor, value] for tenor, value in par.items()],
        "zero": _zero_coupon(strips),
    }
    ENGINE_OUT.mkdir(parents=True, exist_ok=True)
    # One [tenor, value] pair per line.
    text = re.sub(r"\[\s+(\S+),\s+(\S+)\s+\]", r"[\1, \2]", json.dumps(curve, indent=1))
    target = ENGINE_OUT / f"fbil_curve_{CURVE_DAY}.json"
    target.write_text(text + "\n", encoding="utf-8", newline="\n")
    return {
        "fbil_gsec_list.json": get(f"{FBIL}/gsec/fetchfiltered?{window}"),
        f"fbil_gsec_{CURVE_DAY}.xlsx": gsec,
        # A legacy .xls workbook (FBIL served these until 10 Feb 2023): the intermeeting hike.
        "fbil_gsec_2022-05-04.xls": get(f"{FBIL}/gsec/downloadPublished?date=2022-05-04"),
    }


def mcp_call(arguments: dict[str, object]) -> bytes:
    """One ``get_data`` call to MoSPI's MCP server, the raw (event-stream) response body."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "get_data", "arguments": arguments},
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    time.sleep(1.0)
    request = urllib.request.Request(
        MOSPI_MCP, data=json.dumps(payload).encode(), headers={"User-Agent": UA, **headers}
    )
    with _opener.open(request, timeout=90) as response:
        return bytes(response.read())


def mospi_files() -> dict[str, bytes]:
    common = {"series": "Current", "sector_code": "3"}
    return {
        "mospi_cpi2012_2025.txt": mcp_call(
            {
                "dataset": "CPI",
                "filters": common
                | {
                    "base_year": "2012", "year": "2025", "state_code": "99", "limit": "100",
                    "subgroup_code": "0.99,1.99,2.99,3.99,4.99,5.99,6.99",
                },
            }
        ),
        "mospi_cpi2024_2026-02.txt": mcp_call(
            {
                "dataset": "CPI",
                "filters": common
                | {
                    "base_year": "2024", "year": "2026", "month_code": "2", "state_code": "1",
                    "division_code": "0,1,2,3,4,5,6,7,8,9,10,11,12", "limit": "40", "page": "1",
                },
            }
        ),
        "mospi_gdp2022_growth.txt": mcp_call(
            {
                "dataset": "NAS",
                "filters": {
                    "base_year": "2022-23", "series": "Current", "frequency_code": "Quarterly",
                    "indicator_code": "22", "year": "2025-26,2026-27", "limit": "100",
                },
            }
        ),
    }  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["gsec", "mospi"], help="record just these fixtures")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.only == "gsec":
        write(gsec_files())
        return
    if args.only == "mospi":
        write(mospi_files())
        return
    files: dict[str, bytes] = {"rbi_home.html": get("https://www.rbi.org.in/")}
    june_2025 = archive_month(2025, 6)
    files["rbi_archive_2025_06.html"] = june_2025
    eras = {
        "rbi_mmo_2026-10-16.html": (2026, 10, "October 16, 2026"),
        "rbi_mmo_2025-06-16.html": (2025, 6, "June 16, 2025"),
        # A holiday (Dussehra): markets shut, two-day MSF/SDF legs outstanding from the Monday.
        "rbi_mmo_2023-10-24.html": (2023, 10, "October 24, 2023"),
        "rbi_mmo_2022-06-15.html": (2022, 6, "June 15, 2022"),
    }
    for name, (year, month, title) in eras.items():
        listing = june_2025 if (year, month) == (2025, 6) else archive_month(year, month)
        files[name] = get(f"{RBI_PR}?prid={mmo_prid(listing, title)}")
    window = "fromDate=2026-10-01&toDate=2026-10-16&authenticated=false"
    files["fbil_tbill.json"] = get(f"{FBIL}/tbill/fetchfiltered?{window}")
    files["fbil_ovnmibor.json"] = get(f"{FBIL}/ovnmibor/fetchfiltered?{window}")
    files["fbil_refrates.json"] = get(
        f"{FBIL}/refrates/fetchfiltered?fromDate=2026-10-12&toDate=2026-10-12&authenticated=false"
    )
    files["nsdl_monthly.html"] = get("https://www.fpi.nsdl.co.in/web/Reports/Monthly.aspx")
    write(files | gsec_files() | mospi_files())


def write(files: dict[str, bytes]) -> None:
    for name, content in files.items():
        (OUT / name).write_bytes(content)
        print(f"wrote {name} ({len(content):,} bytes)")


if __name__ == "__main__":
    main()
