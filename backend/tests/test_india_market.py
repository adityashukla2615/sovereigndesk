"""India money market: the corridor, participation limits, RBI operations and the calendar."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta

import numpy as np
import pytest

from app.sim.india_market import (
    IST,
    IndiaMarket,
    IndiaModelParams,
    Notice,
    is_business_day,
)
from tests.support import make_india_anchors

TUESDAY = datetime(2026, 10, 20, 1, 0, tzinfo=IST)


def market(
    start: datetime = TUESDAY, params: IndiaModelParams | None = None, **anchors: object
) -> IndiaMarket:
    return IndiaMarket(make_india_anchors(**anchors), np.random.default_rng(5), start, params)


def run(m: IndiaMarket, until: datetime, step: timedelta = timedelta(minutes=15)) -> list[Notice]:
    """Advance in steps, asserting the invariants after every one (as the simulator does)."""
    notices: list[Notice] = []
    t = m.now
    while t < until:
        t = min(t + step, until)
        notices += m.advance(t)
        m.check_invariants()
    return notices


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), IST)


def test_the_opening_position_reproduces_the_release() -> None:
    m = market()
    a = m.anchors
    assert m.projected_surplus() == pytest.approx(a.surplus, rel=1e-9)
    assert m.surplus_pct() == pytest.approx(a.surplus_pct)
    assert m.outstanding("VRRR") == pytest.approx(a.vrrr_outstanding)
    net = m.standing_last["sdf"] - m.standing_last["msf"]  # banks' own positions net out
    assert net == pytest.approx(a.surplus - a.vrrr_outstanding)
    assert m.standing_last["msf"] > 0  # some banks start short even in a surplus
    assert sum(b.bank.ndtl for b in m.books.values()) == pytest.approx(a.ndtl)
    assert m.fortnight == (date(2026, 10, 16), date(2026, 10, 31))


def test_wacr_stays_in_the_corridor_through_tax_season_and_policy_moves() -> None:
    start = datetime(2026, 12, 1, 1, 0, tzinfo=IST)
    m = market(start=start, params=IndiaModelParams(mode="policy"))
    # Policy moves just after midnight, so each day's prints share one corridor.
    notices = run(m, at(date(2026, 12, 11), 0, 30), step=timedelta(hours=2))
    m.set_repo(+0.0025)
    notices += run(m, at(date(2026, 12, 21), 0, 30), step=timedelta(hours=2))
    m.set_repo(-0.0050)
    notices += run(m, at(date(2027, 1, 10), 0), step=timedelta(hours=2))
    traded = [d for d in m.history if d.wacr is not None]
    assert len(traded) >= 20
    for d in traded:  # every day's WACR inside that day's corridor (repo ∓ 25 bp)
        assert d.wacr is not None
        assert d.repo - 0.0025 - 1e-12 <= d.wacr <= d.repo + 0.0025 + 1e-12
        assert d.low is not None
        assert d.high is not None
        assert d.repo - 0.0025 - 1e-12 <= d.low <= d.high <= d.repo + 0.0025 + 1e-12
    texts = [n.text for n in notices if n.code == "TAX"]
    assert any(t.startswith("Advance tax season") for t in texts)
    assert any(t.startswith("GST season") for t in texts)
    assert all(not is_business_day(d.day) for d in m.history if d.volume == 0 and d.wacr is None)


def test_participation_limits_trim_orders_and_log_why() -> None:
    m = market(params=IndiaModelParams(reaction=False))
    run(m, at(TUESDAY.date(), 9, 5))
    small = m.books["SFB-04"]
    small.bank = replace(small.bank, capital_funds=1_000.0)
    big = m.books["PSB-01"]
    # Payments move ₹20,000 cr out of the small bank (zero-sum, so the identity still holds).
    shortfall = small.gap + 20_000.0
    small.balance -= shortfall
    big.balance += shortfall
    # Orders pace the gap over the day, so the cap binds from the second round on.
    run(m, at(TUESDAY.date(), 9, 35))
    rejected = [r for r in m.rejections if r.bank == "SFB-04"]
    assert rejected
    assert rejected[0].side == "borrow"
    assert "daily cap 1,250 cr would be exceeded" in rejected[0].reason
    assert small.borrowed <= 1_250 + 1e-6  # 125% of capital funds
    run(m, at(TUESDAY.date(), 18, 0))
    assert small.msf > 0  # the rest goes to the MSF in the evening
    panel = m.call_panel()
    assert any(r["bank"] == "SFB-04" for r in panel["rejections"])


def test_an_ordered_vrr_injects_and_reverses() -> None:
    # A system in deficit: the latest release shows RBI injecting ₹2 lakh crore on net.
    m = market(params=IndiaModelParams(reaction=False), surplus=-200_000.0, vrrr_outstanding=0.0)
    run(m, at(TUESDAY.date(), 10, 0))
    runs_at = m.order_auction("VRR", 50_000.0, 7)
    assert runs_at == at(TUESDAY.date(), 10, 15)
    notices = run(m, at(TUESDAY.date(), 10, 20))
    (result,) = [n for n in notices if n.code == "VRR"]
    assert result.data["allotted"] == pytest.approx(50_000.0)
    assert result.data["cut_off"] > m.repo
    assert result.data["weighted_average"] >= result.data["cut_off"]
    assert m.outstanding("VRR") == pytest.approx(50_000.0)
    later = run(m, at(TUESDAY.date() + timedelta(days=7), 1, 0), step=timedelta(hours=1))
    assert m.outstanding("VRR") == 0
    assert any(n.code == "LAF" and n.text.startswith("VRR") for n in later)
    with pytest.raises(ValueError, match="tenor"):
        m.order_auction("VRRR", 10_000.0, 0)


def test_a_crr_change_waits_for_the_next_fortnight() -> None:
    m = market(params=IndiaModelParams(reaction=False))
    book = m.books["PSB-01"]
    before = book.requirement
    start, liquidity = m.schedule_crr(0.035)
    assert start == date(2026, 11, 1)  # after the fortnight of 16-31 Oct
    assert liquidity == pytest.approx(-0.005 * m.ndtl())
    run(m, at(date(2026, 10, 31), 23, 0), step=timedelta(hours=3))
    assert book.requirement == pytest.approx(before)
    notices = run(m, at(date(2026, 11, 1), 1, 0), step=timedelta(hours=1))
    assert m.crr == 0.035
    assert book.requirement == pytest.approx(before * 0.035 / 0.03 * m.ndtl_scale, rel=1e-9)
    assert any(n.code == "CRR" and "3.00% → 3.50%" in n.text for n in notices)


def test_a_repo_move_shifts_the_whole_corridor() -> None:
    m = market(params=IndiaModelParams(reaction=False, mode="policy"))
    run(m, at(TUESDAY.date(), 11, 0))
    centre = m.map_rate()
    m.set_repo(+0.0025)
    assert (m.sdf, m.repo, m.msf) == pytest.approx((0.055, 0.0575, 0.06))
    assert m.map_rate() == pytest.approx(min(centre + 0.0025, m.msf))
    run(m, at(TUESDAY.date(), 12, 0))
    assert all(r.lower == pytest.approx(0.055) for r in m.rounds[-4:])


def test_weekends_have_no_call_market_but_the_sdf_stays_open() -> None:
    friday = datetime(2026, 10, 23, 1, 0, tzinfo=IST)
    m = market(start=friday)
    run(m, at(date(2026, 10, 26), 8, 0))
    by_day = {d.day: d for d in m.history}
    assert by_day[date(2026, 10, 23)].volume > 0
    for weekend in (date(2026, 10, 24), date(2026, 10, 25)):
        assert by_day[weekend].wacr is None
        assert by_day[weekend].volume == 0
    assert m.standing_last["sdf"] > 0  # Sunday night's SDF
    # Friday's loans stay out over the weekend and are repaid on Monday.
    assert sum(b.borrowed for b in m.books.values()) == 0


def test_tax_days_drain_what_the_data_says() -> None:
    quiet = IndiaModelParams(reaction=False, idio_sd=0.0)
    m = market(start=datetime(2026, 11, 17, 1, 0, tzinfo=IST), params=quiet, noise_sd=0.0)
    run(m, at(date(2026, 11, 17), 23, 59), step=timedelta(hours=1))
    before = m.history[-1].surplus
    run(m, at(date(2026, 11, 22), 23, 59), step=timedelta(hours=1))
    after = m.history[-1].surplus
    assert before - after == pytest.approx(m.anchors.tax.gst_drain, rel=1e-6)


def test_panels() -> None:
    m = market()
    run(m, at(TUESDAY.date(), 12, 0))
    snap = m.snapshot()
    assert snap["session_open"] is True
    assert snap["corridor"] == {"sdf": 0.0525, "repo": 0.055, "msf": 0.0575}
    assert 0 < snap["call"]["rounds"] == len(m.rounds) <= 12  # rounds that traded
    assert set(snap["tbills"]) == {"3M", "6M", "12M"}
    corridor = m.corridor_panel()
    rates = [p["rate"] for p in corridor["curve"]]
    assert rates == sorted(rates, reverse=True)  # more surplus, lower rate
    band = corridor["band"]
    assert corridor["mode"] == "realistic"
    assert band["lower"] == pytest.approx(0.0525 - 0.0113)  # the lowest print below the SDF
    assert all(band["lower"] <= r <= band["upper"] for r in rates)
    assert snap["tbills_stale"] == "STALE 8d"  # FBIL's benchmarks are from 12 Oct
    banks = m.banks_panel()
    assert len(banks) == 40
    assert {"PD"} <= {b["kind"] for b in banks}
    heat = m.heatmap()
    assert heat["tax_days"][0]["date"] == "2026-10-20"  # inside the GST window, 18-22 Oct
    laf = m.laf_panel()
    assert 0 < laf["reaction"]["vrrr_probability"] < 1


def test_realistic_mode_lets_wacr_stray_as_far_as_it_has() -> None:
    """Deep surplus pushes WACR below the SDF, a deficit above the MSF; never past the extremes."""
    for surplus, outside in ((900_000.0, "below"), (-300_000.0, "above")):  # within history
        m = market(params=IndiaModelParams(reaction=False), surplus=surplus, vrrr_outstanding=0.0)
        run(m, at(date(2026, 11, 13), 23, 59), step=timedelta(hours=2))
        days = [d for d in m.history if d.wacr is not None]
        assert days
        lower, upper = m.band()
        assert all(lower - 1e-12 <= d.wacr <= upper + 1e-12 for d in days if d.wacr is not None)
        if outside == "below":
            assert any(d.wacr is not None and d.wacr < m.sdf for d in days)
        else:
            assert any(d.wacr is not None and d.wacr > m.msf for d in days)
    m.set_mode("policy")
    assert m.band() == (m.sdf, m.msf)
