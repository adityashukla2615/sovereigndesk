"""India sources on recorded responses: RBI homepage and Money Market Operations, FBIL, NSDL."""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qsl

import httpx2
import pytest
from tenacity import wait_none

from app.data.http import Fetcher, RawCache
from app.data.sources.base import FetchOutcome, SourceError
from app.data.sources.fbil import FbilAdapter, parse_mibor, parse_tbill, tbill_tenor
from app.data.sources.nsdl import NsdlAdapter, parse_monthly
from app.data.sources.rbi import (
    RbiAdapter,
    archive_form,
    parse_home,
    parse_mmo,
    parse_release_links,
)
from tests.support import json_response, query

FIXTURES = Path(__file__).parent / "fixtures" / "india"
NOW = datetime(2025, 6, 20, 5, 0, tzinfo=UTC)  # 10:30 in Mumbai
Handler = Callable[[httpx2.Request], httpx2.Response]


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fetcher(handler: Handler, cache_dir: Path, now: datetime = NOW) -> Fetcher:
    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return Fetcher(
        client,
        RawCache(cache_dir),
        attempts=1,
        wait=wait_none(),
        clock=lambda: now,
        sleep=lambda _: None,
    )


def series(outcome: FetchOutcome, series_id: str) -> list[tuple[date, float]]:
    (frame,) = [f for f in outcome.frames if f.spec.series_id == series_id]
    return [(d, float(v)) for d, v in zip(frame.data["date"], frame.data["value"], strict=True)]


def assert_liquidity_identity(values: dict[str, float]) -> None:
    """RBI's row F: injections (MSF, VRR, long-term repos, SLF) less absorptions (SDF, VRRR)."""
    injected = sum(
        values.get(k, 0.0) for k in ("msf_amount", "vrr_amount", "ltro_amount", "slf_amount")
    )
    absorbed = sum(values.get(k, 0.0) for k in ("sdf_amount", "vrrr_amount"))
    assert values["net_liquidity"] == pytest.approx(injected - absorbed, abs=0.005)


# ----------------------------------------------------------------------- RBI parsers


def test_home_rates_with_the_reference_rate_dated_by_the_page() -> None:
    rates = parse_home(fixture("rbi_home.html"))
    assert rates.values == {
        "repo": 5.5,
        "sdf": 5.25,
        "msf": 5.75,
        "bank_rate": 5.75,
        "fixed_reverse_repo": 3.35,
        "crr": 3.0,
        "slr": 18.0,
        "usdinr": 94.7691,
    }
    # "(As at 1.00pm of October 19, 2026)"; the T-bill cut-offs carry no date and are skipped.
    assert rates.dated == {"usdinr": date(2026, 10, 19)}
    undated = parse_home(b"<p>Policy Repo Rate : 5.50% INR / 1 USD : 94.7691</p>")
    assert undated.values == {"repo": 5.5}
    with pytest.raises(SourceError, match="no policy repo rate"):
        parse_home(b"<html>maintenance</html>")


def test_mmo_2026_counts_every_tenor_and_outstanding_leg() -> None:
    report = parse_mmo(fixture("rbi_mmo_2026-10-16.html"))
    v = report.values
    assert report.as_of == date(2026, 10, 16)
    assert (v["call_rate"], v["call_low"], v["call_high"], v["call_volume"]) == (
        5.39,
        4.90,
        5.90,
        1475.35,
    )
    assert (v["treps_rate"], v["market_repo_rate"], v["notice_rate"]) == (5.76, 5.00, 5.81)
    assert "term_rate" not in v  # RBI prints no weighted rate for term money
    # Friday: 1-, 2- and 3-day legs. MSF 8,316 + 0 + 0; SDF 1,58,474 + 0 + 1,141.
    assert (v["msf_amount"], v["msf_rate"]) == (8316.0, 5.75)
    assert (v["sdf_amount"], v["sdf_rate"]) == (159615.0, 5.25)
    assert v["vrrr_amount"] == 18170.0 + 38655.0  # two reverse repos outstanding
    assert v["slf_amount"] == 8476.05
    assert v["net_liquidity"] == -199647.95
    assert_liquidity_identity(v)
    assert v["crr_requirement"] == 833309.0
    assert (v["crr_balance"], report.dated["crr_balance"]) == (844129.11, date(2026, 10, 16))
    assert (v["durable_liquidity"], report.dated["durable_liquidity"]) == (
        1014401.0,
        date(2026, 9, 30),
    )


def test_mmo_2022_with_the_long_term_repo_family_and_numeric_dates() -> None:
    report = parse_mmo(fixture("rbi_mmo_2022-06-15.html"))
    v = report.values
    assert (report.as_of, v["call_rate"], v["treps_volume"]) == (date(2022, 6, 15), 4.54, 405673.70)
    # LTRO 1,530 + TLTRO 65,668 + TLTRO 2.0 7,450 + on-tap TLTRO 9,045 + SLTRO 3,055; the LTRO
    # rows after the first leave the label cell empty, the SLTRO rows span it.
    assert v["ltro_amount"] == pytest.approx(86748.0)
    assert v["vrrr_amount"] == 64965.0 + 33456.0
    assert v["net_liquidity"] == -346261.57
    assert_liquidity_identity(v)
    # This era writes dates as dd/mm/yyyy.
    assert report.dated == {
        "crr_balance": date(2022, 6, 15),
        "gov_surplus_cash": date(2022, 6, 15),
        "durable_liquidity": date(2022, 5, 20),
    }


def test_mmo_on_a_holiday_has_no_rates_but_counts_earlier_legs() -> None:
    report = parse_mmo(fixture("rbi_mmo_2023-10-24.html"))  # Dussehra
    v = report.values
    assert report.as_of == date(2023, 10, 24)
    assert "call_rate" not in v
    assert v["call_volume"] == 0.0
    assert v["msf_amount"] == 8668.0 + 138595.0  # today's plus Monday's two-day MSF
    assert v["sdf_amount"] == 8390.0 + 50046.0
    assert (v["msf_rate"], v["sdf_rate"]) == (6.75, 6.25)
    assert v["ltro_amount"] == pytest.approx(9045.0 + 3055.0)
    assert v["net_liquidity"] == 98754.23
    assert_liquidity_identity(v)
    assert report.dated["gov_surplus_cash"] == date(2023, 10, 23)
    assert report.dated["durable_liquidity"] == date(2023, 10, 6)


def test_mmo_2025() -> None:
    report = parse_mmo(fixture("rbi_mmo_2025-06-16.html"))
    assert (report.as_of, report.values["call_rate"]) == (date(2025, 6, 16), 5.30)
    assert_liquidity_identity(report.values)
    assert report.dated["durable_liquidity"] == date(2025, 5, 30)


def test_mmo_rejects_other_pages() -> None:
    with pytest.raises(SourceError, match="not a Money Market Operations release"):
        parse_mmo(fixture("rbi_home.html"))
    with pytest.raises(SourceError, match="no overnight money-market segment"):
        parse_mmo(b"<p>Money Market Operations as on June 16, 2025</p>")


def test_archive_links_and_form() -> None:
    page = fixture("rbi_archive_2025_06.html")
    links = parse_release_links(page)
    assert len(links) == 31  # a release for every calendar day, weekends included
    assert (min(links), max(links)) == (date(2025, 5, 30), date(2025, 6, 29))
    form = archive_form(page, 2025, 5)
    assert (form["hdnYear"], form["hdnMonth"], form["UsrFontCntr$btn"]) == ("2025", "5", "")
    assert {"__VIEWSTATE", "__EVENTVALIDATION"} <= set(form)
    with pytest.raises(SourceError, match=r"no ASP\.NET form state"):
        archive_form(b"<html></html>", 2025, 5)


# ----------------------------------------------------------------------- RBI adapter

JUNE_16 = parse_release_links(fixture("rbi_archive_2025_06.html"))[date(2025, 6, 16)]
MAY_PAGE = (
    b"<a class='link2' href=BS_PressReleaseDisplay.aspx?prid=1>"
    b"Money Market Operations as on May 29, 2025</a>"
)


class FakeRbi:
    """RBI's site: homepage, the press-release page, the archive by POST, one real release."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.forms: list[dict[str, str]] = []
        self.down = False
        self.releases: Iterator[bytes] | None = None
        self.listing = fixture("rbi_archive_2025_06.html")  # lists 30 May to 29 Jun
        self.archive = {"5": MAY_PAGE, "6": fixture("rbi_archive_2025_06.html")}

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        prid = query(request).get("prid")
        self.requests.append(f"{request.method} {prid or request.url.path}")
        if self.down:
            return httpx2.Response(503)
        if request.url.path == "/":
            return httpx2.Response(200, content=fixture("rbi_home.html"))
        if request.method == "POST":
            form = dict(parse_qsl(request.content.decode()))
            self.forms.append(form)
            return httpx2.Response(200, content=self.archive.get(form["hdnMonth"], b""))
        if prid is None:
            return httpx2.Response(200, content=self.listing)
        if prid == JUNE_16:
            body = next(self.releases) if self.releases else fixture("rbi_mmo_2025-06-16.html")
            return httpx2.Response(200, content=body)
        return httpx2.Response(404)


def test_rbi_adapter_crawls_the_archive_and_reuses_saved_releases(tmp_path: Path) -> None:
    site = FakeRbi()
    adapter = RbiAdapter(fetcher(site, tmp_path), pause_s=0)
    outcome = adapter.fetch(start=date(2025, 5, 29), end=date(2025, 6, 16))

    # The listing page reaches back to 30 May, so only May goes through the archive form.
    (form,) = site.forms
    assert (form["hdnYear"], form["hdnMonth"]) == ("2025", "5")
    assert series(outcome, "rbi/repo") == [(date(2025, 6, 20), 5.5)]  # in force when read
    assert series(outcome, "rbi/mmo/wacr") == [(date(2025, 6, 16), 5.30)]
    assert series(outcome, "rbi/mmo/durable_liquidity") == [(date(2025, 5, 30), 584684.0)]
    assert not any(f.provenance.from_cache for f in outcome.frames)
    # Missing releases are reported per day without losing the rest.
    assert len(outcome.errors) == 18
    assert "mmo 2025-05-29" in outcome.errors

    adapter.fetch(start=date(2025, 6, 16), end=date(2025, 6, 16))
    assert site.requests.count(f"GET {JUNE_16}") == 1  # the second run parsed the saved copy


def test_rbi_adapter_posts_for_days_before_the_listing_page_starts(tmp_path: Path) -> None:
    # Like RBI's page: only the latest days, plus the ASP.NET state the archive form needs.
    site = FakeRbi()
    site.listing = (
        b'<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="v" />'
        b"<a href=BS_PressReleaseDisplay.aspx?prid=" + JUNE_16.encode() + b">"
        b"Money Market Operations as on June 16, 2025</a>"
    )
    adapter = RbiAdapter(fetcher(site, tmp_path), pause_s=0)
    outcome = adapter.fetch(start=date(2025, 6, 10), end=date(2025, 6, 16))
    assert [f["hdnMonth"] for f in site.forms] == ["6"]  # the current month, from its start
    assert series(outcome, "rbi/mmo/wacr") == [(date(2025, 6, 16), 5.30)]
    assert sorted(outcome.errors) == [f"mmo 2025-06-{d}" for d in range(10, 16)]

    site.forms.clear()
    adapter.fetch(start=date(2025, 6, 16), end=date(2025, 6, 16))
    assert site.forms == []  # the listing page already covers it


def test_rbi_adapter_falls_back_to_saved_pages_marked_cached(tmp_path: Path) -> None:
    site = FakeRbi()
    adapter = RbiAdapter(fetcher(site, tmp_path), pause_s=0)
    adapter.fetch(start=date(2025, 6, 16), end=date(2025, 6, 16))
    site.down = True
    outcome = adapter.fetch(start=date(2025, 6, 16), end=date(2025, 6, 16))
    assert series(outcome, "rbi/mmo/wacr") == [(date(2025, 6, 16), 5.30)]
    assert all(f.provenance.from_cache for f in outcome.frames)


def test_a_saved_release_that_does_not_parse_is_downloaded_again(tmp_path: Path) -> None:
    site = FakeRbi()
    site.releases = iter([b"<html>Service Unavailable</html>", fixture("rbi_mmo_2025-06-16.html")])
    adapter = RbiAdapter(fetcher(site, tmp_path), pause_s=0)
    first = adapter.fetch(start=date(2025, 6, 16), end=date(2025, 6, 16))
    assert "not a Money Market Operations release" in first.errors["mmo 2025-06-16"]
    second = adapter.fetch(start=date(2025, 6, 16), end=date(2025, 6, 16))
    assert series(second, "rbi/mmo/wacr") == [(date(2025, 6, 16), 5.30)]
    assert site.requests.count(f"GET {JUNE_16}") == 2


# ----------------------------------------------------------------------- FBIL


def test_fbil_parsers() -> None:
    assert [tbill_tenor(n) for n in ("7 Days", "1 Month", "12 Months", "Overnight")] == [
        "7D",
        "1M",
        "12M",
        None,
    ]
    tbills = parse_tbill(fixture("fbil_tbill.json"))
    assert len(tbills) == 14
    assert (date(2026, 10, 12), 5.31) in tbills["7D"]
    mibor = parse_mibor(fixture("fbil_ovnmibor.json"))
    assert (date(2026, 10, 12), 5.46) in mibor
    assert (date(2026, 10, 1), 5.10) in mibor  # a four-day fixing over the holiday


def test_fbil_adapter_windows(tmp_path: Path) -> None:
    windows: list[tuple[str, str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        q = query(request)
        assert q["authenticated"] == "false"
        product = request.url.path.split("/")[-2]
        if product == "tbill":
            windows.append((q["fromDate"], q["toDate"]))
        return json_response(fixture(f"fbil_{product}.json"))

    outcome = FbilAdapter(fetcher(handler, tmp_path), pause_s=0).fetch(
        start=date(2026, 8, 1), end=date(2026, 10, 16)
    )
    assert windows == [
        ("2026-08-01", "2026-08-31"),
        ("2026-09-01", "2026-10-01"),
        ("2026-10-02", "2026-10-16"),
    ]
    assert series(outcome, "fbil/usdinr") == [(date(2026, 10, 12), 95.7485)]
    assert (date(2026, 10, 12), 5.31) in series(outcome, "fbil/tbill/7D")
    assert not outcome.errors


# ----------------------------------------------------------------------- NSDL


def test_nsdl_monthly_flows() -> None:
    flows = parse_monthly(fixture("nsdl_monthly.html"))
    assert len(flows["equity_inr"]) == 12
    assert flows["equity_inr"][0] == (date(2026, 10, 1), -9231.88)  # printed "(9231.88)"
    assert flows["total_inr"][0] == (date(2026, 10, 1), -9507.95)
    assert flows["total_inr"][-1] == (date(2026, 10, 19), 5040.53)
    general, vrr, far = (dict(flows[f"debt_{r}_inr"]) for r in ("general", "vrr", "far"))
    for day, debt in flows["debt_inr"]:
        assert debt == pytest.approx(general[day] + vrr[day] + far[day], abs=0.006)
    with pytest.raises(SourceError, match="no daily FPI rows"):
        parse_monthly(b"<table></table>")


def test_nsdl_adapter(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=fixture("nsdl_monthly.html"))

    outcome = NsdlAdapter(fetcher(handler, tmp_path)).fetch()
    ids = {f.spec.series_id for f in outcome.frames}
    assert {"nsdl/fpi/equity_inr", "nsdl/fpi/debt_usd", "nsdl/fpi/total_inr"} <= ids
    assert not any("mutual_funds" in i for i in ids)  # parsed, but not catalogued
