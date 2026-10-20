"""A uniform-price call money auction: borrowers' bids against lenders' offers at one rate.

Each clearing round collects every bank's order: a borrower states the most it will pay, a
lender the least it will take. The auction matches the most eager borrowers with the cheapest
lenders for as long as a bid still covers an offer, and every trade in the round settles at a
single rate, the midpoint of the marginal bid and offer. Orders strictly inside the margin are
filled in full; orders at the marginal rate share what is left pro rata.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Order:
    bank: str
    amount: float
    """₹ crore, positive."""
    rate: float
    """Decimal: a borrower's maximum or a lender's minimum."""


@dataclass(frozen=True, slots=True)
class Clearing:
    rate: float | None
    """The round's single clearing rate; None when no bid covers any offer."""
    volume: float
    borrowed: dict[str, float] = field(default_factory=dict)
    lent: dict[str, float] = field(default_factory=dict)


def _fills(
    orders: Sequence[Order], volume: float, marginal: float, better: int
) -> dict[str, float]:
    """Full fills strictly better than the marginal rate; the rest pro rata at it."""
    inside = [o for o in orders if better * (o.rate - marginal) > 1e-15]
    at_margin = [o for o in orders if abs(o.rate - marginal) <= 1e-15]
    fills: dict[str, float] = {}
    for o in inside:
        fills[o.bank] = fills.get(o.bank, 0.0) + o.amount
    left = volume - sum(o.amount for o in inside)
    margin_total = sum(o.amount for o in at_margin)
    if left > 1e-9 and margin_total > 0:
        for o in at_margin:
            fills[o.bank] = fills.get(o.bank, 0.0) + left * o.amount / margin_total
    return fills


def clear_call(bids: Sequence[Order], offers: Sequence[Order]) -> Clearing:
    """Clear one round of the call market at a single rate.

    Equation:
        bids ranked by rate (descending), offers ascending; walk both while bidᵢ ≥ offerⱼ,
        matching q = min(remaining bidᵢ, remaining offerⱼ)
        V = Σ q,   r* = (b_m + a_m)/2 for the marginal bid b_m and offer a_m
        orders better than the margin fill in full; orders at the margin share the rest pro rata
    """
    if any(o.amount <= 0 for o in (*bids, *offers)):
        raise ValueError("order amounts must be positive")
    b = sorted(bids, key=lambda o: -o.rate)
    a = sorted(offers, key=lambda o: o.rate)
    i = j = 0
    left_b = b[0].amount if b else 0.0
    left_a = a[0].amount if a else 0.0
    volume = 0.0
    marginal: tuple[float, float] | None = None
    while i < len(b) and j < len(a) and b[i].rate >= a[j].rate:
        q = min(left_b, left_a)
        volume += q
        marginal = (b[i].rate, a[j].rate)
        left_b -= q
        left_a -= q
        if left_b <= 1e-12:
            i += 1
            left_b = b[i].amount if i < len(b) else 0.0
        if left_a <= 1e-12:
            j += 1
            left_a = a[j].amount if j < len(a) else 0.0
    if marginal is None:
        return Clearing(None, 0.0)
    bid_m, offer_m = marginal
    return Clearing(
        rate=(bid_m + offer_m) / 2,
        volume=volume,
        borrowed=_fills(b, volume, bid_m, better=+1),
        lent=_fills(a, volume, offer_m, better=-1),
    )
