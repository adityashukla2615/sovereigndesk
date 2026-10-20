from collections import Counter
from datetime import date

import numpy as np
import pytest

from sovereign_engine.india.banks import (
    Bank,
    UniverseSpec,
    borrowing_caps,
    crr_change_liquidity,
    crr_daily_floor,
    crr_requirement,
    fortnight_crr_shortfall,
    generate_universe,
    implied_ndtl,
    lending_caps,
    limit_check,
    limit_room,
    msf_capacity,
    ndtl_change_liquidity,
)
from sovereign_engine.india.rules import (
    CITATIONS,
    CRR_SCHEDULE,
    MoneyMarketRules,
    crr_on,
    fortnight,
)

RULES = MoneyMarketRules(crr=0.03, slr=0.18)
NDTL = implied_ndtl(833_309.0, 0.03)  # RBI MMO, fortnight ending 31 Oct 2026


def test_implied_ndtl_from_the_reported_requirement() -> None:
    ndtl = implied_ndtl(833_309.0, 0.03)
    assert ndtl == pytest.approx(27_776_966.67, rel=1e-9)  # about ₹278 lakh crore


def test_universe_adds_up_to_real_ndtl() -> None:
    banks = generate_universe(NDTL, RULES, np.random.default_rng(1))
    assert len(banks) == 40
    assert sum(b.ndtl for b in banks) == pytest.approx(NDTL, rel=1e-12)
    by_kind = Counter(b.kind for b in banks)
    assert by_kind == {"PSB": 12, "PVT": 16, "FGN": 6, "SFB": 4, "PD": 2}
    shares = {
        k: sum(b.ndtl for b in banks if b.kind == k) / NDTL for k in ("PSB", "PVT", "FGN", "SFB")
    }
    assert shares == pytest.approx(UniverseSpec().ndtl_share)
    assert len({b.code for b in banks}) == 40
    psbs = [b for b in banks if b.kind == "PSB"]
    assert psbs[0].code == "PSB-01"
    assert psbs[0].ndtl == max(b.ndtl for b in psbs)
    assert all(b.slr_holdings >= RULES.slr * b.ndtl for b in banks)
    assert all(b.ndtl == 0 and b.capital_funds > 0 for b in banks if b.kind == "PD")


def test_universe_is_reproducible() -> None:
    a = generate_universe(NDTL, RULES, np.random.default_rng(7))
    b = generate_universe(NDTL, RULES, np.random.default_rng(7))
    assert a == b


BANK = Bank("PVT-01", "PVT", ndtl=1_000_000.0, capital_funds=130_000.0, slr_holdings=220_000.0)
DEALER = Bank("PD-01", "PD", ndtl=0.0, capital_funds=2_000.0, slr_holdings=0.0)


def test_reserve_rules() -> None:
    assert crr_requirement(BANK, RULES) == pytest.approx(30_000)
    assert crr_daily_floor(BANK, RULES) == pytest.approx(29_700)  # 99% from 16 Oct 2026
    assert fortnight_crr_shortfall([30_500, 29_800, 29_900], 30_000) == pytest.approx(0)
    assert fortnight_crr_shortfall([29_000] * 14, 30_000) == pytest.approx(1_000)
    old_rules = MoneyMarketRules(crr=0.03, slr=0.18, crr_daily_min_share=0.90)
    assert crr_daily_floor(BANK, old_rules) == pytest.approx(27_000)


def test_msf_capacity_is_excess_slr_plus_the_dip() -> None:
    # Excess SLR 220,000 − 180,000 = 40,000, plus the 2% dip 20,000.
    assert msf_capacity(BANK, RULES) == pytest.approx(60_000)
    assert msf_capacity(DEALER, RULES) == 0


def test_participation_caps() -> None:
    assert borrowing_caps(BANK, RULES) == pytest.approx((130_000, 162_500))
    avg, peak = borrowing_caps(DEALER, RULES)
    assert avg == pytest.approx(4_500)
    assert peak is None  # RBI states no daily maximum for PDs
    assert lending_caps(BANK, RULES) == pytest.approx((32_500, 65_000))


def test_limit_check_rejects_with_reasons() -> None:
    avg, peak = borrowing_caps(BANK, RULES)

    def check(outstanding: float, proposed: float, used: float, days: int = 14) -> str | None:
        return limit_check(
            outstanding=outstanding,
            proposed=proposed,
            fortnight_sum=used,
            avg_cap=avg,
            peak_cap=peak,
            fortnight_days=days,
        )

    assert check(0, 100_000, 0) is None
    over_peak = check(100_000, 70_000, 0)
    assert over_peak is not None
    assert "daily cap" in over_peak
    # Twelve days at 150,000 use 1,800,000 of a 14-day fortnight's budget of 14 × 130,000.
    used = 12 * 150_000
    assert check(0, 20_000, used) is None
    over_avg = check(0, 50_000, used)
    assert over_avg is not None
    assert "fortnightly average" in over_avg
    # A 16-day half-month fortnight (16-31 Oct) has room for 2 × 130,000 more.
    assert check(0, 50_000, used, days=16) is None
    pd_avg, _ = borrowing_caps(DEALER, RULES)
    pd_check = limit_check(
        outstanding=0,
        proposed=60_000,
        fortnight_sum=0,
        avg_cap=pd_avg,
        peak_cap=None,
        fortnight_days=15,
    )
    assert pd_check is None


def test_liquidity_from_reserve_changes() -> None:
    # A 25 bp CRR cut on ₹278 lakh crore releases about ₹69,000 crore.
    assert crr_change_liquidity(NDTL, 0.03, 0.0275) == pytest.approx(69_442.4, rel=1e-4)
    assert ndtl_change_liquidity(100_000, 0.03) == pytest.approx(-3_000)


def test_every_rule_is_cited() -> None:
    assert len(CITATIONS) == 10
    assert all(c.url.startswith("https://") for c in CITATIONS)
    with pytest.raises(ValueError, match="fractions"):
        MoneyMarketRules(crr=3.0, slr=0.18)


def test_reporting_fortnights_follow_rbi_2025_26_148() -> None:
    # Half-months from 16 Dec 2025: the first half is always 15 days, the second 13 to 16.
    assert fortnight(date(2026, 10, 20)) == (date(2026, 10, 16), date(2026, 10, 31))
    assert fortnight(date(2026, 10, 15)) == (date(2026, 10, 1), date(2026, 10, 15))
    assert fortnight(date(2026, 2, 20)) == (date(2026, 2, 16), date(2026, 2, 28))
    assert fortnight(date(2025, 12, 16)) == (date(2025, 12, 16), date(2025, 12, 31))
    # The three-day transition, and the Saturday-to-Friday fortnights before it.
    assert fortnight(date(2025, 12, 14)) == (date(2025, 12, 13), date(2025, 12, 15))
    assert fortnight(date(2025, 12, 12)) == (date(2025, 11, 29), date(2025, 12, 12))
    for start, _ in CRR_SCHEDULE[1:]:  # every CRR change took effect on a fortnight's first day
        assert fortnight(start)[0] == start


def test_crr_schedule() -> None:
    assert crr_on(date(2022, 5, 20)) == 0.04
    assert crr_on(date(2022, 5, 21)) == 0.045
    assert crr_on(date(2024, 12, 20)) == 0.0425
    assert crr_on(date(2025, 10, 10)) == 0.035
    assert crr_on(date(2026, 10, 20)) == 0.03
    with pytest.raises(ValueError, match="no CRR on record"):
        crr_on(date(2021, 1, 1))


def _room(outstanding: float, used: float, carry: int = 1) -> float:
    avg, peak = borrowing_caps(BANK, RULES)
    return limit_room(
        outstanding=outstanding,
        fortnight_sum=used,
        avg_cap=avg,
        peak_cap=peak,
        fortnight_days=14,
        carry_days=carry,
    )


def _check(proposed: float, used: float, carry: int = 1) -> str | None:
    avg, peak = borrowing_caps(BANK, RULES)
    return limit_check(
        outstanding=0,
        proposed=proposed,
        fortnight_sum=used,
        avg_cap=avg,
        peak_cap=peak,
        fortnight_days=14,
        carry_days=carry,
    )


def test_limit_room_is_the_largest_trade_that_passes() -> None:
    assert _room(100_000, 0) == pytest.approx(62_500)  # the 125% daily cap binds
    used = 12 * 150_000
    room = _room(0, used)
    assert room == pytest.approx(20_000)  # the fortnightly average binds
    assert _check(room, used) is None
    assert _check(room + 1, used) is not None
    assert _room(200_000, 0) == 0.0


def test_a_friday_loan_counts_for_the_whole_weekend() -> None:
    used = 12 * 130_000  # 260,000 of the fortnight's 14 × 130,000 budget left
    assert _room(0, used) == pytest.approx(162_500)  # a weekday: the daily cap binds
    assert _room(0, used, carry=3) == pytest.approx(260_000 / 3)  # Friday: the average binds
    assert _check(100_000, used) is None
    reason = _check(100_000, used, carry=3)
    assert reason is not None
    assert "fortnightly average" in reason
