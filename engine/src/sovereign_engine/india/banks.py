"""A synthetic bank universe scaled to India's real aggregate NDTL, and the rules it must obey.

Every bank here is SYNTHETIC: generic codes (PSB-03, PVT-11, FGN-02, SFB-01, PD-01), sizes drawn
from a lognormal within each group and rescaled so the group totals match the configured shares
of the real aggregate NDTL. Amounts are ₹ crore.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from sovereign_engine.india.rules import MoneyMarketRules

BankKind = Literal["PSB", "PVT", "FGN", "SFB", "PD"]
DEPOSIT_TAKERS: tuple[BankKind, ...] = ("PSB", "PVT", "FGN", "SFB")


@dataclass(frozen=True, slots=True)
class Bank:
    code: str
    kind: BankKind
    ndtl: float
    """Net demand and time liabilities; 0 for standalone primary dealers (not banks)."""
    capital_funds: float
    """Tier 1 + Tier 2 capital for banks; net owned funds (NOF) for primary dealers."""
    slr_holdings: float
    """SLR-eligible securities held; the excess over the requirement backs repo and MSF."""


@dataclass(frozen=True, slots=True)
class UniverseSpec:
    """Shape of the synthetic universe (all ASSUMPTIONS, listed in ASSUMPTIONS.md)."""

    counts: Mapping[BankKind, int] = field(
        default_factory=lambda: {"PSB": 12, "PVT": 16, "FGN": 6, "SFB": 4, "PD": 2}
    )
    ndtl_share: Mapping[BankKind, float] = field(
        default_factory=lambda: {"PSB": 0.55, "PVT": 0.39, "FGN": 0.045, "SFB": 0.015}
    )
    capital_to_ndtl: Mapping[BankKind, float] = field(
        default_factory=lambda: {"PSB": 0.085, "PVT": 0.13, "FGN": 0.10, "SFB": 0.14}
    )
    size_sigma: float = 0.8
    excess_slr: float = 0.045
    """Mean SLR holdings above the requirement, as a fraction of NDTL."""
    pd_nof_range: tuple[float, float] = (1_500.0, 4_000.0)

    def __post_init__(self) -> None:
        if not math.isclose(sum(self.ndtl_share.values()), 1.0):
            raise ValueError("NDTL shares of the deposit-taking groups must sum to 1")


def generate_universe(
    total_ndtl: float,
    rules: MoneyMarketRules,
    rng: np.random.Generator,
    spec: UniverseSpec | None = None,
) -> list[Bank]:
    """Draw a synthetic universe whose NDTL adds up exactly to ``total_ndtl``.

    Equation:
        within group g:  sᵢ ~ LogNormal(0, σ),   NDTLᵢ = share_g · NDTL_total · sᵢ / Σ_{j∈g} sⱼ
        capital fundsᵢ = k_g · NDTLᵢ,   SLR holdingsᵢ = (SLR + e·uᵢ) · NDTLᵢ,  uᵢ ~ U(0.5, 1.5)
        primary dealers: NDTL = 0, NOF ~ U(NOF_lo, NOF_hi)
    """
    spec = spec or UniverseSpec()
    if total_ndtl <= 0:
        raise ValueError("aggregate NDTL must be positive")
    banks: list[Bank] = []
    for kind in DEPOSIT_TAKERS:
        n = spec.counts.get(kind, 0)
        if n == 0:
            continue
        sizes = rng.lognormal(0.0, spec.size_sigma, n)
        ndtl = spec.ndtl_share[kind] * total_ndtl * sizes / sizes.sum()
        ndtl = ndtl[np.argsort(-ndtl)]  # PSB-01 is the largest
        for i, value in enumerate(ndtl, start=1):
            slr_share = rules.slr + spec.excess_slr * float(rng.uniform(0.5, 1.5))
            banks.append(
                Bank(
                    code=f"{kind}-{i:02d}",
                    kind=kind,
                    ndtl=float(value),
                    capital_funds=float(spec.capital_to_ndtl[kind] * value),
                    slr_holdings=float(slr_share * value),
                )
            )
    lo, hi = spec.pd_nof_range
    for i in range(1, spec.counts.get("PD", 0) + 1):
        banks.append(Bank(f"PD-{i:02d}", "PD", 0.0, float(rng.uniform(lo, hi)), 0.0))
    return banks


def crr_requirement(bank: Bank, rules: MoneyMarketRules) -> float:
    """Average daily cash balance a bank must keep with RBI over the fortnight.

    Equation:
        CRR_req = CRR · NDTL
    """
    return rules.crr * bank.ndtl


def crr_daily_floor(bank: Bank, rules: MoneyMarketRules) -> float:
    """Minimum cash balance on any single day of the fortnight.

    Equation:
        floor = m · CRR · NDTL,   m = 0.99 from the fortnight beginning 16 Oct 2026 (was 0.90)
    """
    return rules.crr_daily_min_share * crr_requirement(bank, rules)


def fortnight_crr_shortfall(daily_balances: Sequence[float], requirement: float) -> float:
    """How far the fortnight's average balance falls short of the requirement (0 if met).

    Equation:
        shortfall = max(0, CRR_req − (1/N)·Σ_d balance_d)
    """
    if not daily_balances:
        raise ValueError("need at least one day of balances")
    return max(0.0, requirement - float(np.mean(daily_balances)))


def slr_requirement(bank: Bank, rules: MoneyMarketRules) -> float:
    """SLR securities a bank must hold.

    Equation:
        SLR_req = SLR · NDTL
    """
    return rules.slr * bank.ndtl


def msf_capacity(bank: Bank, rules: MoneyMarketRules) -> float:
    """Most a bank can borrow overnight under the MSF against SLR securities.

    Equation:
        cap = max(0, H − SLR·NDTL) + d·NDTL,   d = 2% (dip below the SLR allowed for MSF)
    """
    if bank.kind == "PD":
        return 0.0
    return (
        max(0.0, bank.slr_holdings - slr_requirement(bank, rules)) + rules.msf_slr_dip * bank.ndtl
    )


def borrowing_caps(bank: Bank, rules: MoneyMarketRules) -> tuple[float, float | None]:
    """Call/notice borrowing caps: (fortnightly-average cap, single-day cap or None). RBI sets
    them for small finance banks and primary dealers; scheduled commercial banks use
    board-approved limits, assumed at the caps RBI set for them before June 2023.

    Equation:
        SFBs:  avg = 1.00·CF,  peak = 1.25·CF        primary dealers:  avg = 2.25·NOF, no daily cap
        other banks (assumed):  avg = 1.00·CF,  peak = 1.25·CF
    """
    if bank.kind == "PD":
        return rules.pd_borrow_avg * bank.capital_funds, None
    if bank.kind == "SFB":
        return rules.sfb_borrow_avg * bank.capital_funds, rules.sfb_borrow_peak * bank.capital_funds
    return rules.scb_borrow_avg * bank.capital_funds, rules.scb_borrow_peak * bank.capital_funds


def lending_caps(bank: Bank, rules: MoneyMarketRules) -> tuple[float, float]:
    """Board-approved internal lending limits (an assumption: RBI prescribes none).

    Equation:
        avg = ℓ_avg·CF,   peak = ℓ_peak·CF
    """
    return rules.lend_avg * bank.capital_funds, rules.lend_peak * bank.capital_funds


def limit_check(
    *,
    outstanding: float,
    proposed: float,
    fortnight_sum: float,
    avg_cap: float,
    peak_cap: float | None,
    fortnight_days: int,
    carry_days: int = 1,
) -> str | None:
    """Why a new call/notice trade would breach a participation limit, or ``None`` if it fits.

    The average test keeps the fortnight attainable: even if the remaining days carried
    nothing, the fortnight's daily average must not exceed the cap. N is the reporting
    fortnight's length (13 to 16 days since half-month fortnights; see ``rules.fortnight``),
    and c the days the position stays outstanding within it (3 for a Friday loan repaid on
    Monday, as non-working days count at the previous day's balance).

    Equation:
        peak:     b + q ≤ peak_cap
        average:  Σ_{past days} b_d + c·(b + q) ≤ avg_cap · N
    """
    after = outstanding + proposed
    if peak_cap is not None and after > peak_cap + 1e-9:
        return f"daily cap {peak_cap:,.0f} cr would be exceeded ({after:,.0f} cr)"
    if fortnight_sum + carry_days * after > avg_cap * fortnight_days + 1e-9:
        return f"fortnightly average cap {avg_cap:,.0f} cr would be exceeded"
    return None


def limit_room(
    *,
    outstanding: float,
    fortnight_sum: float,
    avg_cap: float,
    peak_cap: float | None,
    fortnight_days: int,
    carry_days: int = 1,
) -> float:
    """The largest further trade both participation limits still allow (0 if none).

    Equation:
        room = max(0, min(peak_cap − b,  (avg_cap·N − Σ_{past days} b_d)/c − b))
    """
    room = (avg_cap * fortnight_days - fortnight_sum) / carry_days - outstanding
    if peak_cap is not None:
        room = min(room, peak_cap - outstanding)
    return max(0.0, room)


def crr_change_liquidity(total_ndtl: float, old_crr: float, new_crr: float) -> float:
    """Liquidity released (+) or drained (−) by a CRR change, ₹ crore.

    Equation:
        ΔL = −(CRR_new − CRR_old) · NDTL
    """
    return -(new_crr - old_crr) * total_ndtl


def ndtl_change_liquidity(delta_ndtl: float, crr: float) -> float:
    """Liquidity drained (−) when NDTL grows, because more cash must be held with RBI.

    Equation:
        ΔL = −CRR · ΔNDTL
    """
    return -crr * delta_ndtl


def implied_ndtl(crr_requirement_total: float, crr: float) -> float:
    """Aggregate NDTL implied by the reserve requirement RBI reports for the fortnight.

    Equation:
        NDTL = CRR_req / CRR
    """
    if crr <= 0:
        raise ValueError("CRR must be positive")
    return crr_requirement_total / crr
