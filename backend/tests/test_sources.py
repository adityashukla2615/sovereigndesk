"""Adapters parse recorded real responses (tests/fixtures/sources) without touching the network."""

import json
from datetime import date
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from app.data.catalog import FISCAL_SERIES, FRED_SERIES, tic_series_id
from app.data.sources.base import SourceError
from app.data.sources.fiscaldata import FiscalDataAdapter
from app.data.sources.fred import FredAdapter, parse_observations
from app.data.sources.tic import TicAdapter, parse_current, parse_history
from app.data.sources.treasury import TreasuryCurveAdapter, parse_par_curve_csv
from tests.support import fixture_bytes, json_response, make_fetcher, query

KEY = SecretStr("fake" * 8)

# ----------------------------------------------------------------------- FRED


def test_fred_drops_missing_observations() -> None:
    points = parse_observations(fixture_bytes("fred_dgs10.json"))
    assert date(2026, 10, 12) not in {d for d, _ in points}  # Columbus Day: "."
    assert points[0] == (date(2026, 10, 5), 5.31)
    assert points[-1] == (date(2026, 10, 15), 5.10)


def test_fred_adapter_isolates_failing_series(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if query(request)["series_id"] == "DGS10":
            return json_response(fixture_bytes("fred_dgs10.json"))
        return json_response({"error_code": 400, "error_message": "Bad Request"}, status=400)

    specs = tuple(s for s in FRED_SERIES if s.remote in ("DGS10", "DGS30"))
    outcome = FredAdapter(make_fetcher(handler, tmp_path), KEY, specs).fetch()
    assert [f.spec.series_id for f in outcome.frames] == ["fred/DGS10"]
    assert "fred/DGS30" in outcome.errors
    provenance = outcome.frames[0].provenance
    assert KEY.get_secret_value() not in provenance.url
    assert "series_id=DGS10" in provenance.url


def test_fred_needs_a_key(tmp_path: Path) -> None:
    adapter = FredAdapter(make_fetcher(lambda r: httpx2.Response(500), tmp_path), None)
    with pytest.raises(SourceError, match="FRED_API_KEY"):
        adapter.fetch()


# ----------------------------------------------------------------------- Treasury par curve


def test_treasury_csv_maps_columns_by_name_across_eras() -> None:
    new = parse_par_curve_csv(fixture_bytes("treasury_2026.csv"))
    old = parse_par_curve_csv(fixture_bytes("treasury_2017.csv"))
    assert {"1.5 Month", "4 Mo", "2 Mo"} <= set(new)
    assert not {"1.5 Month", "4 Mo", "2 Mo"} & set(old)  # those tenors did not exist yet
    assert new["10 Yr"][0] == (date(2026, 10, 16), 5.09)
    assert old["30 Yr"][0] == (date(2017, 12, 29), 2.74)


def test_treasury_adapter_builds_one_frame_per_tenor(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        year = query(request)["field_tdr_date_value"]
        name = {"2026": "treasury_2026.csv", "2017": "treasury_2017.csv"}[year]
        return httpx2.Response(200, content=fixture_bytes(name))

    outcome = TreasuryCurveAdapter(make_fetcher(handler, tmp_path)).fetch(
        start=date(2026, 10, 14), end=date(2026, 10, 31)
    )
    frames = {f.spec.series_id: f for f in outcome.frames}
    assert len(frames) == 14
    ten = frames["ust/par/10Y"].data
    assert list(ten["date"]) == [date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)]


# ----------------------------------------------------------------------- FiscalData


def _fiscal_handler(request: httpx2.Request) -> httpx2.Response:
    path, params = request.url.path, query(request)
    if path.endswith("/debt_to_penny"):
        return json_response(fixture_bytes(f"debt_to_penny_p{params['page[number]']}.json"))
    if path.endswith("/avg_interest_rates"):
        return json_response(fixture_bytes("avg_interest_rates.json"))
    if path.endswith("/interest_expense"):
        return json_response(fixture_bytes("interest_expense.json"))
    if path.endswith("/mspd_table_3_market"):
        if params.get("sort") == "-record_date":
            return json_response(fixture_bytes("mspd_latest.json"))
        payload = json.loads(fixture_bytes("mspd_rows.json"))
        payload["meta"]["total-pages"] = 1  # the recording is page 1 of 149; serve it alone
        return json_response(payload)
    return httpx2.Response(404)


def test_fiscaldata_paginates_and_builds_series(tmp_path: Path) -> None:
    outcome = FiscalDataAdapter(make_fetcher(_fiscal_handler, tmp_path)).fetch()
    assert not outcome.errors
    frames = {f.spec.series_id: f.data for f in outcome.frames}
    assert set(frames) == {s.series_id for s in FISCAL_SERIES}
    debt = frames["fiscal/debt/total"]
    assert list(debt["date"]) == [date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 13)]
    assert (debt["value"] > 3e13).all()  # dollars, not millions
    assert float(frames["fiscal/avg_rate/marketable"]["value"].iloc[0]) == 3.518
    public = float(frames["fiscal/interest/public_issues"]["value"].iloc[0])
    total = float(frames["fiscal/interest/total"]["value"].iloc[0])
    assert 0 < public < total


def test_mspd_snapshot_keeps_issue_level_rows(tmp_path: Path) -> None:
    snapshot = FiscalDataAdapter(make_fetcher(_fiscal_handler, tmp_path)).mspd_latest()
    first = snapshot.rows[0]
    assert (first.record_date, first.cusip, first.security_class) == (
        date(2026, 9, 30),
        "912797SA6",
        "Bills Maturity Value",
    )
    # Treasury reports a CUSIP's outstanding amount on its first issue row only.
    by_cusip = [r.outstanding_musd for r in snapshot.rows if r.cusip == "912797SA6"]
    assert by_cusip[0] == pytest.approx(334135.4294)
    assert all(v is None for v in by_cusip[1:])


# ----------------------------------------------------------------------- TIC


def test_tic_current_table() -> None:
    holdings = parse_current(fixture_bytes("tic_slt_table5.txt"))
    assert holdings["Japan"][date(2026, 8, 31)] == 1068.3
    assert {"Grand Total", "Of Which: Foreign Official"} <= set(holdings)
    assert (
        tic_series_id("Of Which: Foreign Official T-Bonds & Notes")
        == "tic/foreign_official_t_bonds_and_notes"
    )
    assert tic_series_id("China, Mainland") == "tic/china_mainland"


def test_tic_history_blocks() -> None:
    holdings = parse_history(fixture_bytes("tic_mfhhis01.txt"))
    japan = holdings["Japan"]
    assert japan[date(2025, 12, 31)] == 1185.5
    assert japan[date(2024, 1, 31)] > 0  # second yearly block parsed too
    assert "China, Mainland" in holdings  # quoted labels unquoted


def test_tic_adapter_prefers_the_current_table(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("slt_table5.txt"):
            return httpx2.Response(200, content=fixture_bytes("tic_slt_table5.txt"))
        # Pretend the history file holds an unrevised Dec 2025 figure for Japan.
        stale = fixture_bytes("tic_mfhhis01.txt").replace(b"Japan\t1185.5", b"Japan\t9999.9")
        return httpx2.Response(200, content=stale)

    outcome = TicAdapter(make_fetcher(handler, tmp_path)).fetch()
    frames = {f.spec.series_id: f.data for f in outcome.frames}
    japan = dict(zip(frames["tic/japan"]["date"], frames["tic/japan"]["value"], strict=True))
    assert japan[date(2025, 12, 31)] == 1185.5  # the current table's figure wins
    assert japan[date(2026, 8, 31)] == 1068.3
    assert min(japan) <= date(2024, 1, 31)  # history still fills the earlier months
