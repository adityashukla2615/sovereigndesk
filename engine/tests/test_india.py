from collections import Counter

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
    msf_capacity,
    ndtl_change_liquidity,
)
from sovereign_engine.india.rules import CITATIONS, MoneyMarketRules

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
    assert (
        limit_check(outstanding=0, proposed=100_000, fortnight_sum=0, avg_cap=avg, peak_cap=peak)
        is None
    )
    over_peak = limit_check(
        outstanding=100_000, proposed=70_000, fortnight_sum=0, avg_cap=avg, peak_cap=peak
    )
    assert over_peak is not None
    assert "daily cap" in over_peak
    # Twelve days at 150,000 use 1,800,000 of the fortnight's budget of 14 × 130,000 = 1,820,000.
    used = 12 * 150_000
    assert (
        limit_check(outstanding=0, proposed=20_000, fortnight_sum=used, avg_cap=avg, peak_cap=peak)
        is None
    )
    over_avg = limit_check(
        outstanding=0, proposed=50_000, fortnight_sum=used, avg_cap=avg, peak_cap=peak
    )
    assert over_avg is not None
    assert "fortnightly average" in over_avg
    pd_avg, _ = borrowing_caps(DEALER, RULES)
    assert (
        limit_check(outstanding=0, proposed=60_000, fortnight_sum=0, avg_cap=pd_avg, peak_cap=None)
        is None
    )


def test_liquidity_from_reserve_changes() -> None:
    # A 25 bp CRR cut on ₹278 lakh crore releases about ₹69,000 crore.
    assert crr_change_liquidity(NDTL, 0.03, 0.0275) == pytest.approx(69_442.4, rel=1e-4)
    assert ndtl_change_liquidity(100_000, 0.03) == pytest.approx(-3_000)


def test_every_rule_is_cited() -> None:
    assert len(CITATIONS) == 3
    assert all(c.url.startswith("https://") for c in CITATIONS)
    with pytest.raises(ValueError, match="fractions"):
        MoneyMarketRules(crr=3.0, slr=0.18)
