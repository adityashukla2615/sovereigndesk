"""RBI's policy record: decisions, meeting schedules, T-bill cut-offs and money markets of every
era, parsed from recorded press releases, and the adapter that crawls them."""

import re
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qsl

import httpx2
import pytest

from app.data.sources.base import SourceError
from app.data.sources.rbi import parse_mmo
from app.data.sources.rbi_policy import (
    Decision,
    RbiPolicyAdapter,
    Reserves,
    is_decision_title,
    is_lending_rates_title,
    is_schedule_title,
    is_tbill_title,
    is_wss_title,
    merge_meetings,
    parse_decision,
    parse_listing,
    parse_mclr,
    parse_mmo_summary,
    parse_reserves,
    parse_schedule,
    parse_tbill_cutoff,
)
from tests.support import make_fetcher, query

FIXTURES = Path(__file__).parent / "fixtures" / "india"


def page(name: str) -> bytes:
    return (FIXTURES / f"{name}.html").read_bytes()


@pytest.mark.parametrize(
    ("name", "decision"),
    [
        ("rbi_policy_2014-04-01", Decision(8.0, 8.0, 0.0)),  # the Governor's statement, a hold
        ("rbi_policy_2015-01-15", Decision(7.75, 8.0, 25.0)),  # an intermeeting cut
        ("rbi_policy_2020-03-27", Decision(4.4, 5.15, 75.0)),  # "to 4.40 ... from 5.15"
        ("rbi_policy_2023-06-08", Decision(6.5, 6.5, 0.0)),  # an MPC hold
        ("rbi_policy_2025-08-06", Decision(5.5, 5.5, 0.0)),  # "maintain ... at"
        ("rbi_policy_2026-10-07", Decision(5.5, None, 25.0)),  # an MPC hike
    ],
)
def test_reads_the_repo_decision_in_every_era(name: str, decision: Decision) -> None:
    assert parse_decision(page(name)) == decision


def test_a_release_without_a_decision_gives_none() -> None:
    assert parse_decision(page("rbi_mpc_schedule_2026-27")) is None


def test_titles_pick_decisions_schedules_and_bill_results() -> None:
    assert is_decision_title("Statement by Dr. Raghuram G Rajan, Governor on Monetary Policy")
    assert is_decision_title(
        "Monetary Policy Statement, 2026-27 Resolution of the Monetary Policy Committee "
        "October 5 to 7, 2026"
    )
    assert is_decision_title("Fourth Bi-monthly Monetary Policy Statement, 2015-16")
    for title in (
        "First Bi-monthly Monetary Policy Statement, 2015-16 on April 7, 2015",
        "Fifth Bi-monthly Monetary Policy Statement 2016-17 on at 2.30 pm on December 07, 2016",
        "RBI to announce Sixth Bi-monthly Monetary Policy Review, 2015-16 on Tuesday, Feb 02, 2016",
        "Minutes of the Monetary Policy Committee Meeting, June 4 to 6, 2025",
        "Statement on Developmental and Regulatory Policies",
    ):
        assert not is_decision_title(title), title
    assert is_schedule_title("Meeting Schedule of the Monetary Policy Committee for 2026-2027")
    assert is_schedule_title("Meeting of the Monetary Policy Committee – Rescheduled")
    assert is_tbill_title("91-Days Treasury Bills - Auction Result: Cut off")
    assert is_tbill_title("Treasury Bills: Full Auction Result")
    assert not is_tbill_title("182-Days Treasury Bills - Auction Result: Cut off")
    assert not is_tbill_title("91-day Treasury Bills Auction: ₹ 10,000 crore under Regular Auction")


def test_schedules_give_each_meetings_decision_day() -> None:
    assert parse_schedule(page("rbi_mpc_schedule_2026-27")) == [
        date(2026, 4, 8),
        date(2026, 6, 5),
        date(2026, 8, 5),
        date(2026, 10, 7),
        date(2026, 12, 4),
        date(2027, 2, 5),
    ]
    # A meeting spanning two months, "September 29-30 & October 1, 2020".
    assert date(2020, 10, 1) in parse_schedule(page("rbi_mpc_schedule_2020-21"))
    # Notices that move a meeting: only the new days count, not the old ones, the dates of
    # earlier releases or a holiday's.
    assert parse_schedule(page("rbi_mpc_rescheduled_2022-02")) == [date(2022, 2, 10)]
    assert parse_schedule(page("rbi_mpc_rescheduled_2022-08")) == [date(2022, 8, 5)]
    assert parse_schedule(page("rbi_mpc_rescheduled_2025-08")) == [date(2025, 8, 6)]
    assert parse_schedule(page("rbi_mpc_revised_2018-19")) == [date(2018, 6, 6)]
    assert parse_schedule(page("rbi_mpc_postponed_2020-10")) == []  # "will be announced"


def test_a_later_notice_moves_a_meeting() -> None:
    yearly = parse_schedule(page("rbi_mpc_schedule_2020-21"))
    notices = [parse_schedule(page(f"rbi_mpc_{n}_2020-10")) for n in ("postponed", "notice")]
    meetings = merge_meetings([yearly, *notices])
    assert notices[1] == [date(2020, 10, 9)]  # "October 7 to October 9, 2020"
    assert date(2020, 10, 9) in meetings
    assert date(2020, 10, 1) not in meetings  # the postponed meeting's old day
    assert len(meetings) == len(yearly)


def test_tbill_cut_off_in_both_release_layouts() -> None:
    assert parse_tbill_cutoff(page("rbi_tbill_2015-01-14")) == 8.3946  # "(YTM - 8.3946 %)"
    assert parse_tbill_cutoff(page("rbi_tbill_2017-06-28")) == 6.2735  # per-tenor release
    assert parse_tbill_cutoff(page("rbi_tbill_2022-02-09")) == 3.8887  # "91 Days" column
    assert parse_tbill_cutoff(page("rbi_tbill_2025-06-25")) == 5.4094  # "91-Day" column
    assert parse_tbill_cutoff(page("rbi_tbill_2026-06-03")) == 5.5586  # only the 91-day sold
    assert parse_tbill_cutoff(page("rbi_tbill_2026-03-25")) is None  # every bid rejected
    assert parse_tbill_cutoff(page("rbi_mpc_schedule_2026-27")) is None


def test_money_markets_of_every_era() -> None:
    # 2015: ₹ crore, tenors as "(1 day)", footnote marks on rates, a term-repo leg, and a
    # double space in the title; net liquidity is the sum of the legs, MSF and SLF.
    first = parse_mmo_summary(page("rbi_mmo_2015-01-15"))
    assert first.as_of == date(2015, 1, 15)
    assert (first.wacr, first.call_volume) == (7.88, 13_339.74)
    legs = 20_164 + 13_760 + 15_007 + 18_506 + 15_506 + 15_502 - 1_783 + 20 + 6_305.29
    assert first.net_liquidity == pytest.approx(legs)
    assert first.crr_requirement == 339_218.0
    old = parse_mmo_summary(page("rbi_mmo_2016-10-14"))  # ₹ billion, no net liquidity row
    assert old.as_of == date(2016, 10, 14)
    assert old.wacr == 6.17
    assert old.crr_requirement == pytest.approx(399_643.0)  # ₹3,996.43 billion
    assert old.net_liquidity == pytest.approx(13_749.0)  # summed from the LAF legs
    mid = parse_mmo_summary(page("rbi_mmo_2019-08-14"))
    assert mid.net_liquidity == pytest.approx(-118_720.0)  # as printed (-1,187.20 billion)
    printed = page("rbi_mmo_2019-08-14")
    summed = parse_mmo_summary(re.sub(rb"Net liquidity injected", b"Net (hidden)", printed))
    assert summed.net_liquidity == pytest.approx(mid.net_liquidity)  # the leg sum agrees
    late = parse_mmo_summary(page("rbi_mmo_2021-06-14"))
    assert late.net_liquidity == pytest.approx(-477_307.0)
    assert late.wacr == 3.11
    for name in ("rbi_mmo_2022-06-15", "rbi_mmo_2026-10-16"):  # the daily parser agrees
        summary = parse_mmo_summary(page(name))
        values = parse_mmo(page(name)).values
        assert summary.net_liquidity == pytest.approx(values["net_liquidity"])
        assert summary.crr_requirement == pytest.approx(values["crr_requirement"])
    with pytest.raises(SourceError, match="not a Money Market Operations release"):
        parse_mmo_summary(page("rbi_tbill_2025-06-25"))


@pytest.mark.parametrize(
    ("name", "reserves"),
    [
        # ₹ billion with a "`" for the rupee sign, en dashes for minus and for zero; dates as
        # "As on January 24, 2014", "As on April 1 2016" and "As on Aug. 29, 2025"
        ("rbi_wss_2014-01-31", Reserves(date(2014, 1, 24), 292_238.8, 266_051.9, 19_724.5)),
        ("rbi_wss_2016-04-08", Reserves(date(2016, 4, 1), 359_759.8, 335_686.6, 20_115.0)),
        ("rbi_wss_2019-08-30", Reserves(date(2019, 8, 23), 429_050.8, 397_128.5, 26_867.4)),
        ("rbi_wss_2025-06-27", Reserves(date(2025, 6, 20), 697_935.0, 589_069.0, 85_743.0)),
        ("rbi_wss_2025-09-05", Reserves(date(2025, 8, 29), 694_230.0, 583_937.0, 86_769.0)),
    ],
)
def test_weekly_forex_reserves_in_every_era(name: str, reserves: Reserves) -> None:
    assert parse_reserves(page(name)) == reserves
    assert is_wss_title("Reserve Bank of India – Bulletin Weekly Statistical Supplement – Extract")
    with pytest.raises(SourceError, match="no foreign exchange reserves table"):
        parse_reserves(page("rbi_policy_2026-10-07"))


def test_lending_rates_give_the_median_mclr() -> None:
    assert is_lending_rates_title(
        "Lending and Deposit Rates of Scheduled Commercial Banks – September 2026"
    )
    # "increased from 7.75 per cent in September 2022 to 7.90 per cent in October 2022"
    assert parse_mclr(page("rbi_rates_2022-10")) == {date(2022, 9, 1): 7.75, date(2022, 10, 1): 7.9}
    # "Marginal Cost of fund-based Lending Rate ... moved to 8.79 per cent in May 2024 from ..."
    assert parse_mclr(page("rbi_rates_2024-05")) == {date(2024, 5, 1): 8.79, date(2024, 4, 1): 8.85}
    assert parse_mclr(page("rbi_rates_2026-09")) == {date(2026, 9, 1): 8.61, date(2026, 8, 1): 8.7}
    assert parse_mclr(page("rbi_rates_2022-06")) == {}  # tables only, in an attached file


def test_listing_dates_every_release() -> None:
    entries = parse_listing(page("rbi_archive_2015_01"))
    statement = next(e for e in entries if is_decision_title(e.title))
    assert (statement.day, statement.prid) == (date(2015, 1, 15), "33012")
    assert all(date(2015, 1, 1) <= e.day <= date(2015, 1, 31) for e in entries)


def test_adapter_reads_a_months_decision_and_bill(tmp_path: Path) -> None:
    pages = {"63742": page("rbi_policy_2026-10-07")}
    listing = page("rbi_archive_2026_10")
    bills = {e.prid for e in parse_listing(listing) if is_tbill_title(e.title)}

    def handler(request: httpx2.Request) -> httpx2.Response:
        prid = query(request).get("prid")
        if request.method == "POST" or prid is None:
            return httpx2.Response(200, content=listing)
        if prid in bills:
            return httpx2.Response(200, content=page("rbi_tbill_2025-06-25"))
        return httpx2.Response(200, content=pages.get(prid, b"<html>other release</html>"))

    adapter = RbiPolicyAdapter(make_fetcher(handler, tmp_path), pause_s=0)
    outcome = adapter.fetch(start=date(2026, 10, 1), end=date(2026, 10, 19))
    frames = {f.spec.series_id: f.data for f in outcome.frames}
    repo = frames["rbi/mpc/repo"]
    assert list(repo["date"]) == [date(2026, 10, 7)]
    assert list(repo["value"]) == [5.5]
    assert list(frames["rbi/mpc/scheduled"]["value"]) == [0.0]  # no schedule in this window
    # The latest auction is read for today's features. The 7 Oct auction came after that day's
    # 10:00 announcement, so it does not count as "before" the decision (the 30 Sep one would,
    # but it lies outside the window).
    assert list(frames["rbi/tbill91/cutoff"]["date"]) == [date(2026, 10, 14)]
    assert "rbi/hist/wacr" not in frames  # 2026 is covered by the daily MMO series


def test_a_listing_saved_after_its_month_ended_is_reused(tmp_path: Path) -> None:
    posts: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            form = dict(parse_qsl(request.content.decode()))
            posts.append(f"{form['hdnYear']}-{form['hdnMonth']}")
            name = "rbi_archive_2015_01" if form["hdnYear"] == "2015" else "rbi_archive_2026_10"
            return httpx2.Response(200, content=page(name))
        return httpx2.Response(200, content=page("rbi_archive_2026_10"))

    fetcher = make_fetcher(handler, tmp_path)
    fetcher.clock = lambda: datetime(2026, 10, 20, 5, 0, tzinfo=UTC)
    adapter = RbiPolicyAdapter(fetcher, pause_s=0)
    for _ in range(2):
        january = adapter._listing(date(2015, 1, 1), date(2015, 1, 31))
        adapter._listing(date(2026, 10, 1), date(2026, 10, 19))
    assert any(e.prid == "33012" for e in january)  # the saved copy still lists the month
    # January 2015 is posted once; October 2026, listed while it ran, is posted each time.
    assert posts == ["2015-1", "2026-10", "2026-10"]


def test_adapter_reads_money_markets_up_to_the_daily_series(tmp_path: Path) -> None:
    listing = page("rbi_archive_2026_10")
    mmo = {
        e.prid: e.title
        for e in parse_listing(listing)
        if e.title.startswith("Money Market Operations as on")
    }
    asked: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        prid = query(request).get("prid")
        if request.method == "POST" or prid is None:
            return httpx2.Response(200, content=listing)
        asked.append(prid)
        if prid == "63742":
            return httpx2.Response(200, content=page("rbi_policy_2026-10-07"))
        if prid in mmo:
            return httpx2.Response(200, content=page("rbi_mmo_2026-10-16"))
        return httpx2.Response(200, content=b"<html>other release</html>")

    # Were the daily series to start on 3 Oct, the 7 Oct decision's window (from 23 Sep) would
    # be read up to 2 Oct: the releases as on 30 Sep, 1 Oct and 2 Oct in this listing.
    fetcher = make_fetcher(handler, tmp_path)
    adapter = RbiPolicyAdapter(fetcher, pause_s=0, mmo_before=date(2026, 10, 3))
    outcome = adapter.fetch(start=date(2026, 10, 1), end=date(2026, 10, 19))
    read = sorted(
        mmo[prid].removeprefix("Money Market Operations as on ") for prid in asked if prid in mmo
    )
    assert read == ["October 01, 2026", "October 02, 2026", "September 30, 2026"]
    assert "rbi/hist/wacr" in {f.spec.series_id for f in outcome.frames}


def test_adapter_skips_an_auction_without_a_cut_off(tmp_path: Path) -> None:
    listing = page("rbi_archive_2026_10")
    bills = sorted(
        (e for e in parse_listing(listing) if is_tbill_title(e.title) and e.day.month == 10),
        key=lambda e: e.day,
    )
    rejected = bills[-1].prid  # every bid rejected, as on 25 Mar 2026

    def handler(request: httpx2.Request) -> httpx2.Response:
        prid = query(request).get("prid")
        if request.method == "POST" or prid is None:
            return httpx2.Response(200, content=listing)
        if prid == rejected:
            return httpx2.Response(200, content=page("rbi_tbill_2026-03-25"))
        if prid in {e.prid for e in bills}:
            return httpx2.Response(200, content=page("rbi_tbill_2025-06-25"))
        return httpx2.Response(200, content=b"<html>other release</html>")

    adapter = RbiPolicyAdapter(make_fetcher(handler, tmp_path), pause_s=0)
    outcome = adapter.fetch(start=date(2026, 10, 1), end=date(2026, 10, 19))
    frames = {f.spec.series_id: f.data for f in outcome.frames}
    # Today's features take the auction before the rejected one.
    assert list(frames["rbi/tbill91/cutoff"]["date"]) == [bills[-2].day]
