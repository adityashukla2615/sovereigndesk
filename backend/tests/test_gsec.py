"""India's G-sec curve: FBIL's workbooks, the event-study anchors, the live curve and its panels."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx2
import numpy as np
import pandas as pd
import pytest

from app.commands import execute
from app.commands.registry import CommandResult
from app.data.catalog import FBIL_GSEC_TENORS
from app.data.sources.fbil_gsec import FbilGsecAdapter, parse_par_yields, published_dates
from app.sim.gsec_anchors import (
    COUPON_TENORS,
    RepoEvent,
    daily_coverage_start,
    fit_factors,
    quotes_of,
    repo_events,
)
from app.sim.india_market import IST, IndiaMarket
from app.sim.simulator import Simulator
from sovereign_engine.india.passthrough import PassThrough, PassThroughFit
from sovereign_engine.rates.loadings import expectations_loading, term_premium_loading
from tests.support import (
    Handler,
    json_response,
    make_fetcher,
    make_gsec_anchors,
    make_india_anchors,
    make_us_anchors,
    query,
)

FIXTURES = Path(__file__).parent / "fixtures" / "india"
XLSX = (FIXTURES / "fbil_gsec_2026-10-12.xlsx").read_bytes()
XLS = (FIXTURES / "fbil_gsec_2022-05-04.xls").read_bytes()
LISTING = (FIXTURES / "fbil_gsec_list.json").read_bytes()
TUESDAY = datetime(2026, 10, 20, 1, 0, tzinfo=IST)
LABELS = list(FBIL_GSEC_TENORS)


# ----------------------------------------------------------------------- FBIL's workbooks


def test_parses_the_current_xlsx_workbook() -> None:
    day, curve = parse_par_yields(XLSX)
    assert day == date(2026, 10, 12)
    assert len(curve) == 200
    assert (min(curve), max(curve)) == (0.25, 50.0)
    assert (curve[0.25], curve[2.0], curve[10.0], curve[30.0]) == (5.61, 6.69, 7.41, 7.8)


def test_parses_a_legacy_xls_workbook() -> None:
    """Until 10 Feb 2023 FBIL served .xls files with a 'Par-Yield' sheet and more decimals."""
    day, curve = parse_par_yields(XLS)
    assert day == date(2022, 5, 4)
    assert max(curve) == 40.0
    assert curve[10.0] == pytest.approx(7.38692, abs=1e-5)
    assert curve[0.25] == pytest.approx(4.49141, abs=1e-5)


def test_listing_and_unreadable_files() -> None:
    days = published_dates(LISTING)
    assert days[0] == date(2026, 10, 1)
    assert date(2026, 10, 12) in days
    assert days == sorted(days)
    with pytest.raises(ValueError, match="not a readable workbook"):
        parse_par_yields(b"<html><body>Service unavailable</body></html>")
    with pytest.raises(ValueError, match="larger than expected"):
        parse_par_yields(b"PK" + b"\0" * 6_000_000)


def _fbil(downloads: list[str]) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/gsec/fetchfiltered"):
            return json_response(LISTING)
        day = query(request)["date"]
        downloads.append(day)
        body = {"2026-10-12": XLSX, "2022-05-04": XLS, "2026-10-13": XLSX}.get(day)
        return httpx2.Response(404) if body is None else httpx2.Response(200, content=body)

    return handler


def test_adapter_reads_published_days_and_reuses_saved_workbooks(tmp_path: Path) -> None:
    downloads: list[str] = []
    adapter = FbilGsecAdapter(make_fetcher(_fbil(downloads), tmp_path), pause_s=0)
    outcome = adapter.fetch(
        start=date(2026, 10, 1), end=date(2026, 10, 16), also=[date(2022, 5, 4)]
    )
    frames = {f.spec.series_id: f.data for f in outcome.frames}
    assert set(frames) == {f"fbil/gsec/par/{t}" for t in LABELS}
    ten = frames["fbil/gsec/par/10Y"]
    assert list(ten["date"]) == [date(2022, 5, 4), date(2026, 10, 12)]
    assert ten["value"].iloc[-1] == 7.41
    # Unpublished files fail one by one; a file dated another day is refused.
    assert "gsec 2026-10-05" in outcome.errors
    assert "is dated 2026-10-12" in outcome.errors["gsec 2026-10-13"]
    first = len(downloads)
    adapter.fetch(start=date(2026, 10, 1), end=date(2026, 10, 16), also=[date(2022, 5, 4)])
    again = downloads[first:]
    assert "2026-10-12" not in again  # a saved workbook is parsed, not downloaded again
    assert "2022-05-04" not in again


def test_around_brackets_each_event(tmp_path: Path) -> None:
    adapter = FbilGsecAdapter(make_fetcher(_fbil([]), tmp_path), pause_s=0)
    assert adapter.around([date(2026, 10, 7)]) == [
        date(2026, 10, 6),
        date(2026, 10, 7),
        date(2026, 10, 8),
    ]


# ----------------------------------------------------------------------- anchors


def _par(days: list[date], level: float = 0.07) -> pd.DataFrame:
    rows = [[level + 0.0001 * i + 0.0005 * j for j in range(len(LABELS))] for i in range(len(days))]
    return pd.DataFrame(rows, index=pd.to_datetime(days), columns=LABELS)


def test_repo_events_measure_from_the_previous_publication() -> None:
    days = [date(2025, 6, 2), date(2025, 6, 3), date(2025, 6, 5), date(2025, 6, 6)]
    par = _par(days)
    par.loc[pd.Timestamp("2025-06-06")] -= 0.002
    repo = pd.Series(
        [0.06, 0.06, 0.06, 0.055, 0.055], index=pd.date_range("2025-06-02", periods=5, freq="D")
    )
    (event,) = repo_events(par, repo)
    assert (event.day, event.before) == (date(2025, 6, 5), date(2025, 6, 3))
    assert event.change == pytest.approx(-0.005)
    assert event.moves["10Y"] == pytest.approx(0.0001)
    later = repo.copy()
    later.index = later.index + timedelta(days=1)  # the change lands on 6 June, after a gap
    (event,) = repo_events(par, later)
    assert (event.day, event.before) == (date(2025, 6, 6), date(2025, 6, 5))
    assert event.moves["10Y"] == pytest.approx(0.0001 - 0.002)


def test_daily_coverage_starts_after_the_last_long_gap() -> None:
    days = pd.DatetimeIndex(
        ["2022-05-02", "2022-05-04", "2022-06-07", "2023-02-13", "2023-02-14", "2023-02-20"]
    )
    assert daily_coverage_start(days) == date(2023, 2, 13)
    assert daily_coverage_start(days[3:]) == date(2023, 2, 13)


def test_factor_fit_recovers_the_daily_shocks() -> None:
    rng = np.random.default_rng(7)
    fit = PassThroughFit(PassThrough(0.6, 0.35), 0.0, (0.1, 1.0), (0.0, 0.5), (0.3, 0.8), 10)
    years = np.array([FBIL_GSEC_TENORS[t] for t in COUPON_TENORS])
    level, tp = expectations_loading(years, 0.6), term_premium_loading(years, 7.0)
    n = 600
    shocks = rng.multivariate_normal([0, 0], [[9e-8, -2e-8], [-2e-8, 4e-8]], size=n)
    moves = np.cumsum(shocks[:, :1] * level + shocks[:, 1:] * tp, axis=0)
    days = pd.bdate_range("2024-01-01", periods=n)
    par = pd.DataFrame(0.07, index=days, columns=LABELS)
    par[list(COUPON_TENORS)] += moves
    model = fit_factors(par, [], fit)
    assert model.level_sd == pytest.approx(3e-4, rel=0.1)
    assert model.tp_sd == pytest.approx(2e-4, rel=0.1)
    assert model.correlation == pytest.approx(-2 / 6, abs=0.1)
    assert model.residual_bp < 1e-6
    # Repo-change days are left out: they are the event study's, not noise.
    events = [RepoEvent(d.date(), d.date(), 0.0025, {}) for d in days[1:301]]
    assert fit_factors(par, events, fit).days == n - 1 - 300


def test_quotes_use_bill_and_par_conventions() -> None:
    quotes = quotes_of(dict.fromkeys(LABELS, 0.07))
    kinds = {q.kind for q in quotes[:3]}, {q.kind for q in quotes[3:]}
    assert kinds == ({"bill"}, {"par"})
    assert quotes[0].years == pytest.approx(91 / 365)
    assert quotes[-1].years == 30.0


# ----------------------------------------------------------------------- the live curve


def market(**anchors: object) -> IndiaMarket:
    values: dict[str, object] = {"gsec": make_gsec_anchors(), **anchors}
    return IndiaMarket(make_india_anchors(**values), np.random.default_rng(5), TUESDAY)


def test_a_repo_hike_moves_the_short_end_most() -> None:
    m = market()
    assert m.gsec is not None
    before = dict(m.gsec.points)
    m.set_repo(0.0025)
    moves = {t: (m.gsec.points[t] - before[t]) * 1e4 for t in LABELS}
    assert moves["3M"] == pytest.approx(25.0, abs=1e-9)  # the 3-month bill: one for one
    assert moves["1Y"] == pytest.approx(25 * m.gsec.betas["1Y"], abs=1e-9)
    assert moves["10Y"] == pytest.approx(25 * m.gsec.betas["10Y"], abs=1e-9)
    assert moves["3M"] > moves["2Y"] > moves["10Y"] > 0
    assert moves["30Y"] > 0
    assert m.gsec.fit.rmse_bp < 5
    tbills = m.tbills()
    assert tbills["12M"] - m.anchors.tbills["12M"] == pytest.approx(0.0025 * m.gsec.betas["1Y"])


def test_pass_through_is_measured_from_fbils_day() -> None:
    """FBIL's curve is from 12 Oct; a repo change between then and RBI's latest release is
    already in the opening curve."""
    m = market(gsec=make_gsec_anchors(repo=0.0525))
    assert m.gsec is not None
    shift = m.gsec.points["10Y"] - m.gsec.anchors.par["10Y"]
    assert shift == pytest.approx(0.0025 * m.gsec.betas["10Y"])


def test_curve_moves_in_session_and_closes_daily() -> None:
    m = market()
    assert m.gsec is not None
    opening = dict(m.gsec.points)
    midnight = datetime.combine(TUESDAY.date(), datetime.min.time(), IST)
    for hour in range(9, 25):  # through 23:59, the end of the day
        m.advance(midnight + timedelta(hours=hour))
        m.check_invariants()
    assert m.gsec.points != opening
    assert [c.day for c in m.gsec.history] == [TUESDAY.date()]
    assert m.gsec.history[-1].par == m.gsec.points
    assert m.gsec.fit.rmse_bp < 6


def test_factor_noise_has_the_fitted_daily_size() -> None:
    m = market()
    assert m.gsec is not None
    g, steps = m.gsec, 32 * 400
    levels = []
    for _ in range(steps):
        g.step(1 / 32)
        levels.append(g.level)
    daily = np.diff(np.array(levels)[31::32])
    assert np.std(daily) == pytest.approx(g.anchors.factors.level_sd, rel=0.15)


def test_tick_and_panel() -> None:
    m = market()
    snap = m.snapshot()
    tick = snap["gsec"]
    assert tick is not None
    assert set(tick["points"]) == set(LABELS)
    assert set(tick["nss"]) == {"beta0", "beta1", "beta2", "beta3", "tau1", "tau2"}
    assert tick["stale"] == "STALE 8d"  # FBIL's workbook is from 12 Oct
    panel = m.gsec_panel()
    assert panel is not None
    pt = panel["passthrough"]
    assert len(pt["events"]) == 11
    assert [e["tenor"] for e in pt["estimates"]] == LABELS
    assert pt["estimates"][0]["relative"] == 1.0
    grid = pt["curve"]
    assert grid[0]["years"] == 0.25
    assert grid[0]["beta"] == pytest.approx(1.0)
    for row in grid:
        assert row["beta"] == pytest.approx(row["expectations"] + row["tp"])
    assert panel["close"]["3M"] == 0.0565  # the T-bill benchmark, not FBIL's par-curve point


def test_market_runs_without_a_curve() -> None:
    m = IndiaMarket(make_india_anchors(), np.random.default_rng(5), TUESDAY)
    assert m.gsec is None
    assert m.snapshot()["gsec"] is None
    assert m.tbill_beta == {"3M": 1.0, "6M": 1.0, "12M": 1.0}


# ----------------------------------------------------------------------- commands and SPRD

MORNING = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)  # Tuesday 10:30 in Mumbai


def simulator(gsec: bool = True) -> Simulator:
    sim = Simulator(None, seed=3, clock=lambda: MORNING)
    india = make_india_anchors(gsec=make_gsec_anchors()) if gsec else make_india_anchors()
    sim.load(make_us_anchors(), india)
    sim.tick(3600 / sim.speed)
    return sim


def run(sim: Simulator, text: str) -> CommandResult:
    return asyncio.run(execute(sim, text))


def test_gsec_and_sprd_commands() -> None:
    sim = simulator()
    gsec = run(sim, "GSEC")
    assert gsec.ok, gsec.message
    assert gsec.panel == "GSEC"
    assert gsec.message.startswith("G-secs: 91D ")
    assert "11 repo changes" in gsec.message
    sprd = run(sim, "SPRD")
    assert sprd.ok, sprd.message
    assert sprd.data is not None
    now = sprd.data["now"]
    assert now["spread"] == pytest.approx(now["india"] - now["us"])
    assert 0.01 < now["spread"] < 0.04  # India's 10Y about 2.3 points above the US's
    assert len(sprd.data["real"]) > 30


def test_repo_narrates_the_curve_and_sprd_records_closes() -> None:
    sim = simulator()
    run(sim, "REPO -25BP")
    text = sim.events.recent()[-1].text
    assert "G-secs 2Y −" in text or "G-secs 2Y -" in text
    sim.tick(2 * 86400 / sim.speed)  # two days
    assert [s.day for s in sim.spreads] == [date(2026, 10, 20), date(2026, 10, 21)]
    assert all(s.us is not None for s in sim.spreads)


def test_curve_commands_report_a_missing_curve() -> None:
    sim = simulator(gsec=False)
    for code in ("GSEC", "SPRD"):
        reply = run(sim, code)
        assert not reply.ok
        assert "G-sec curve unavailable" in reply.message
    assert any("G-sec curve unavailable" in e.text for e in sim.events.recent())
