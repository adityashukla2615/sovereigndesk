"""India money-market mechanics: the macro map fit, the call auction and RBI's LAF auctions."""

import numpy as np
import pytest

from sovereign_engine.india.auctions import Bid, run_auction
from sovereign_engine.india.call_market import Order, clear_call
from sovereign_engine.india.liquidity_map import LiquidityMap, fit_liquidity_map
from sovereign_engine.india.reaction import ReactionCurve, fit_reaction

TRUE = LiquidityMap(deficit=0.0025, surplus=-0.0045, midpoint=0.8, width=0.95)


def test_liquidity_map_shape() -> None:
    assert float(TRUE.spread(-10)) == pytest.approx(0.0025, abs=1e-6)
    assert float(TRUE.spread(10)) == pytest.approx(-0.0045, abs=1e-5)
    assert float(TRUE.spread(0.8)) == pytest.approx((0.0025 - 0.0045) / 2)
    grid = np.linspace(-2, 4, 61)
    assert np.all(TRUE.slope(grid) < 0)
    h = 1e-6
    numeric = (TRUE.spread(0.3 + h) - TRUE.spread(0.3 - h)) / (2 * h)
    assert float(TRUE.slope(0.3)) == pytest.approx(float(numeric), rel=1e-6)
    with pytest.raises(ValueError, match="deficit spread"):
        LiquidityMap(deficit=-0.01, surplus=0.01, midpoint=0, width=1)


def test_fit_recovers_the_curve_and_residual_persistence() -> None:
    rng = np.random.default_rng(3)
    x = rng.uniform(-1.7, 4.2, 1000)
    noise = np.zeros(x.size)
    for i in range(1, x.size):  # AR(1) residuals, like WACR's day-to-day deviations
        noise[i] = 0.6 * noise[i - 1] + rng.normal(0, 0.0008)
    fit = fit_liquidity_map(x, TRUE.spread(x) + noise)
    assert fit.curve.deficit == pytest.approx(TRUE.deficit, abs=0.0006)
    assert fit.curve.surplus == pytest.approx(TRUE.surplus, abs=0.0006)
    assert fit.curve.midpoint == pytest.approx(TRUE.midpoint, abs=0.25)
    assert fit.rmse_bp == pytest.approx(10.0, rel=0.15)
    assert fit.residual_ar1 == pytest.approx(0.6, abs=0.08)
    with pytest.raises(ValueError, match="eight"):
        fit_liquidity_map([0.1, 0.2], [0.0, 0.0])


def test_call_auction_clears_at_one_rate() -> None:
    bids = [
        Order("PSB-01", 500, 0.0560),
        Order("PVT-02", 300, 0.0550),
        Order("SFB-01", 200, 0.0530),
    ]
    offers = [Order("PVT-01", 400, 0.0535), Order("FGN-01", 600, 0.0545)]
    c = clear_call(bids, offers)
    # 500 at 5.60 meets 400 at 5.35 and 100 at 5.45; 300 at 5.50 meets 300 more at 5.45.
    assert c.volume == pytest.approx(800)
    assert c.rate == pytest.approx((0.0550 + 0.0545) / 2)
    assert c.borrowed == pytest.approx({"PSB-01": 500, "PVT-02": 300})
    assert c.lent == pytest.approx({"PVT-01": 400, "FGN-01": 400})
    assert sum(c.borrowed.values()) == pytest.approx(sum(c.lent.values()))
    # Every borrower pays no more than it bid, every lender earns at least its offer.
    rate = c.rate
    assert rate is not None
    assert all(o.rate >= rate for o in bids if o.bank in c.borrowed)
    assert all(o.rate <= rate for o in offers if o.bank in c.lent)


def test_call_auction_shares_the_margin_pro_rata() -> None:
    # Lenders clamped to the SDF rate tie at the margin.
    bids = [Order("PSB-01", 300, 0.0560)]
    offers = [Order("A", 400, 0.0525), Order("B", 200, 0.0525)]
    c = clear_call(bids, offers)
    assert c.lent == pytest.approx({"A": 200, "B": 100})
    assert c.rate == pytest.approx((0.0560 + 0.0525) / 2)


def test_call_auction_without_a_cross() -> None:
    c = clear_call([Order("A", 100, 0.0530)], [Order("B", 100, 0.0540)])
    assert (c.rate, c.volume, c.borrowed, c.lent) == (None, 0.0, {}, {})
    assert clear_call([], [Order("B", 1, 0.05)]).rate is None
    with pytest.raises(ValueError, match="positive"):
        clear_call([Order("A", 0, 0.05)], [])


def test_vrr_is_multiple_price_with_pro_rata_at_the_cut_off() -> None:
    repo = 0.0550
    bids = [
        Bid("PSB-01", 30_000, 0.0565),
        Bid("PVT-01", 20_000, 0.0560),
        Bid("PVT-02", 20_000, 0.0558),
        Bid("SFB-01", 20_000, 0.0558),
        Bid("PSB-02", 10_000, 0.0550),  # at the repo rate: rejected
        Bid("FGN-01", 0.5, 0.0570),  # under ₹1 crore: rejected
    ]
    r = run_auction("VRR", 60_000, bids, repo)
    assert r.received == 90_000
    assert r.allotted == pytest.approx(60_000)
    assert r.cut_off == 0.0558
    assert r.by_bank() == pytest.approx(
        {"PSB-01": 30_000, "PVT-01": 20_000, "PVT-02": 5_000, "SFB-01": 5_000}
    )
    # Each pays its own rate, so the weighted average sits above the cut-off.
    expected = (30_000 * 0.0565 + 20_000 * 0.0560 + 10_000 * 0.0558) / 60_000
    assert r.weighted_average == pytest.approx(expected)
    assert {b.bank for b, _ in r.rejected} == {"PSB-02", "FGN-01"}


def test_vrrr_takes_the_cheapest_offers_first() -> None:
    repo = 0.0550
    bids = [Bid("A", 50_000, 0.0540), Bid("B", 50_000, 0.0530), Bid("C", 50_000, 0.0555)]
    r = run_auction("VRRR", 75_000, bids, repo)
    assert r.by_bank() == pytest.approx({"B": 50_000, "A": 25_000})
    assert r.cut_off == 0.0540
    assert r.weighted_average is not None
    assert r.weighted_average < r.cut_off  # each earns its own (lower) rate
    assert [b.bank for b, _ in r.rejected] == ["C"]
    undersubscribed = run_auction("VRRR", 150_000, bids[:2], repo)
    assert undersubscribed.allotted == pytest.approx(100_000)
    with pytest.raises(ValueError, match="notified"):
        run_auction("VRR", 0, bids, repo)


def test_reaction_curve_recovers_a_logistic() -> None:
    rng = np.random.default_rng(11)
    x = rng.uniform(-2, 4, 4000)
    truth = ReactionCurve(-2.0, 0.8)
    y = (rng.uniform(size=x.size) < truth.probability(x)).astype(float)
    fit = fit_reaction(x, y)
    assert fit.intercept == pytest.approx(-2.0, abs=0.15)
    assert fit.slope == pytest.approx(0.8, abs=0.08)
    assert float(fit.probability(10)) > 0.99
    with pytest.raises(ValueError, match="both days"):
        fit_reaction(x[:20], np.zeros(20))
