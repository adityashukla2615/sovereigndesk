"""RBI's variable rate repo (VRR) and reverse repo (VRRR) auctions under the LAF.

The operational guidelines (press releases 2021-2022/1572 for VRR and 2019-2020/1947 for VRRR)
make these multiple-price auctions: bids are ranked (VRR by rate descending, as RBI lends to the
highest bidders; VRRR ascending, as RBI borrows from the cheapest), the cut-off is the rate at
which the notified amount is reached, every successful bid pays or earns its own rate, and bids
at the cut-off share the remainder pro rata. VRR bids at or below the repo rate are rejected,
as are VRRR bids at or above it; the minimum bid is ₹1 crore.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

AuctionKind = Literal["VRR", "VRRR"]
MIN_BID = 1.0
"""₹ crore."""


@dataclass(frozen=True, slots=True)
class Bid:
    bank: str
    amount: float
    """₹ crore."""
    rate: float
    """Decimal."""


@dataclass(frozen=True, slots=True)
class Allotment:
    bank: str
    amount: float
    rate: float


@dataclass(frozen=True, slots=True)
class AuctionResult:
    kind: AuctionKind
    notified: float
    received: float
    """Valid bids, ₹ crore."""
    allotted: float
    cut_off: float | None
    weighted_average: float | None
    allotments: list[Allotment] = field(default_factory=list)
    rejected: list[tuple[Bid, str]] = field(default_factory=list)

    def by_bank(self) -> dict[str, float]:
        """Total allotted to each bank.

        Equation:
            Aᵦ = Σ_{allotments of b} qᵢ
        """
        out: dict[str, float] = {}
        for a in self.allotments:
            out[a.bank] = out.get(a.bank, 0.0) + a.amount
        return out


def run_auction(
    kind: AuctionKind, notified: float, bids: Sequence[Bid], repo: float
) -> AuctionResult:
    """Allot a VRR or VRRR auction the way RBI's operational guidelines describe.

    Equation:
        valid: VRR rᵢ > repo, VRRR rᵢ < repo; qᵢ ≥ 1 crore
        rank VRR by rᵢ descending, VRRR ascending; r_c = rate where Σ qᵢ first reaches N
        bids ahead of r_c: full qᵢ at rᵢ;  bids at r_c: (N − allotted ahead)·qᵢ / Σ q at r_c
        weighted average = Σ allotted·rᵢ / Σ allotted
    """
    if notified <= 0:
        raise ValueError("the notified amount must be positive")
    sign = -1.0 if kind == "VRR" else 1.0
    valid: list[Bid] = []
    rejected: list[tuple[Bid, str]] = []
    for bid in bids:
        if bid.amount < MIN_BID:
            rejected.append((bid, "below the ₹1 crore minimum bid"))
        elif kind == "VRR" and bid.rate <= repo:
            rejected.append((bid, "VRR bids at or below the repo rate are rejected"))
        elif kind == "VRRR" and bid.rate >= repo:
            rejected.append((bid, "VRRR bids at or above the repo rate are rejected"))
        else:
            valid.append(bid)
    received = sum(b.amount for b in valid)
    ranked = sorted(valid, key=lambda b: sign * b.rate)
    allotments: list[Allotment] = []
    cut_off: float | None = None
    filled = 0.0
    k = 0
    while k < len(ranked) and filled < notified - 1e-9:
        rate = ranked[k].rate
        level = [b for b in ranked[k:] if abs(b.rate - rate) <= 1e-12]
        total = sum(b.amount for b in level)
        room = notified - filled
        share = 1.0 if total <= room + 1e-9 else room / total
        allotments += [Allotment(b.bank, b.amount * share, b.rate) for b in level]
        filled += total * share
        cut_off = rate
        k += len(level)
    allotted = sum(a.amount for a in allotments)
    weighted = sum(a.amount * a.rate for a in allotments) / allotted if allotted > 0 else None
    return AuctionResult(
        kind, notified, received, allotted, cut_off, weighted, allotments, rejected
    )
