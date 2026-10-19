"""Record real responses from the Indian sources for the backend's offline parser tests.

    py scripts/record_india_fixtures.py

Writes backend/tests/fixtures/india/ verbatim: the RBI homepage, Money Market Operations
releases from several format eras, one month of the RBI press-release archive, FBIL T-bill and
MIBOR JSON, and NSDL's monthly FPI page. Requests are spaced politely.
"""

import html
import re
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "india"
RBI_PR = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
FBIL = "https://www.fbil.org.in/wasdm"
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
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
    for name, content in files.items():
        (OUT / name).write_bytes(content)
        print(f"wrote {name} ({len(content):,} bytes)")


if __name__ == "__main__":
    main()
