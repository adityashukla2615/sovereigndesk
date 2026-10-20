"""What a yield shock does to a retail investor's bonds and bond funds.

Each bond is repriced exactly from its cash flows at the shocked yield, next to the duration
and duration + convexity estimates; a fund has no cash flows of its own, so only the estimates
from its published modified duration and convexity are available. For a bond, holding to
maturity is set against selling now: held, it pays every coupon and its face value whatever
the market does, and its realised yield is the yield it was bought at plus the gain from
reinvesting the coupons at the new, higher (or lower) yield; sold, the price change is a loss
(or gain) crystallised today.

Amounts are in the holding's currency; yields are decimals with semi-annual compounding, as
Indian and US government bonds quote them.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import FloatArray
from sovereign_engine.bonds.approx import approx_price_change
from sovereign_engine.bonds.cashflows import CashFlows, convexity, dv01, modified_duration, price


@dataclass(frozen=True, slots=True)
class BondHolding:
    name: str
    face: float
    """Face value held."""
    coupon: float
    """Annual coupon rate (decimal)."""
    years: float
    """Years to maturity."""
    yield0: float
    """Today's market yield at its maturity (decimal, semi-annual), before the shock."""
    freq: int = 2

    def cash_flows(self) -> CashFlows:
        """The remaining coupons and the redemption, per 100 face.

        Equation:
            n = ⌈f·T⌉,  w = f·T − (n − 1),  t_k = (w + k)/f,  CF_k = c·100/f (+ 100 at k = n − 1)
        """
        if self.years <= 0 or self.face <= 0:
            raise ValueError(f"{self.name}: need a positive maturity and face value")
        periods = max(1, math.ceil(self.years * self.freq - 1e-9))
        first = self.years * self.freq - (periods - 1)
        return CashFlows.bullet(self.coupon, periods, self.freq, first_period=min(first, 1.0))


@dataclass(frozen=True, slots=True)
class FundHolding:
    name: str
    value: float
    """Units × NAV today."""
    modified_duration: float
    convexity: float


@dataclass(frozen=True, slots=True)
class HoldOutcome:
    """A bond held to maturity against sold today, after the shock."""

    coupons: float
    """Coupons still to be received."""
    redemption: float
    schedule: list[tuple[float, float]]
    """(years from today, amount) of every remaining payment."""
    bought_yield: float
    """The yield at today's price before the shock: what holding to maturity locks in."""
    realised_yield: float
    """With the coupons reinvested at the shocked yield until maturity."""
    sale_proceeds: float
    sale_gain: float
    """Crystallised by selling now (negative: a loss)."""


@dataclass(frozen=True, slots=True)
class HoldingImpact:
    name: str
    kind: str
    """"bond" or "fund"."""
    dy: float
    value0: float
    value1: float
    """After the shock: exact for a bond, the second-order estimate for a fund."""
    exact: float | None
    """Relative price change, exact (bonds only)."""
    duration_only: float
    duration_convexity: float
    modified_duration: float
    convexity: float
    dv01: float
    """Value change for a 1 bp rise in yield (currency, positive)."""
    hold: HoldOutcome | None

    @property
    def change(self) -> float:
        return self.value1 - self.value0


def realised_yield(cf: CashFlows, price0: float, reinvest: float, freq: int = 2) -> float:
    """The yield actually earned by holding to maturity from ``price0``, with every coupon
    reinvested at ``reinvest`` until then (semi-annual).

    Equation:
        FV = Σ_k CF_k·(1 + r/f)^(f·(T − t_k)),   y_R = f·((FV / P₀)^(1/(f·T)) − 1)
    """
    horizon = float(cf.times[-1])
    growth = (1 + reinvest / freq) ** (freq * (horizon - cf.times))
    future = float(cf.amounts @ growth)
    return float(freq * ((future / price0) ** (1 / (freq * horizon)) - 1))


def bond_impact(holding: BondHolding, dy: float) -> HoldingImpact:
    """Reprice one bond for a yield change ``dy``: exact, by duration, by duration + convexity,
    and held to maturity against sold now.

    Equation:
        V = P(y)·F/100;  exact ΔP/P = P(y₀ + Δy)/P(y₀) − 1;  ≈ −D·Δy;  ≈ −D·Δy + ½·C·Δy²;
        DV01 = F/100 · |∂P/∂y|·10⁻⁴
    """
    cf = holding.cash_flows()
    y0, y1, f = holding.yield0, holding.yield0 + dy, holding.freq
    p0, p1 = price(cf, y0, f), price(cf, y1, f)
    scale = holding.face / 100
    d, c = modified_duration(cf, y0, f), convexity(cf, y0, f)
    first, second = -d * dy, float(approx_price_change(d, c, dy))
    hold = HoldOutcome(
        coupons=float(cf.amounts.sum() - 100) * scale,
        redemption=holding.face,
        schedule=[(float(t), float(a) * scale) for t, a in zip(cf.times, cf.amounts, strict=True)],
        bought_yield=y0,
        realised_yield=realised_yield(cf, p0, y1, f),
        sale_proceeds=p1 * scale,
        sale_gain=(p1 - p0) * scale,
    )
    return HoldingImpact(
        name=holding.name,
        kind="bond",
        dy=dy,
        value0=p0 * scale,
        value1=p1 * scale,
        exact=p1 / p0 - 1,
        duration_only=first,
        duration_convexity=second,
        modified_duration=d,
        convexity=c,
        dv01=dv01(cf, y0, f) * scale,
        hold=hold,
    )


def fund_impact(holding: FundHolding, dy: float) -> HoldingImpact:
    """A bond fund's estimated value change from its modified duration and convexity: the fund
    publishes no cash flows, so the second-order estimate is the best available.

    Equation:
        ΔV/V ≈ −D·Δy + ½·C·Δy²;   DV01 = V·D·10⁻⁴
    """
    if holding.value <= 0:
        raise ValueError(f"{holding.name}: need a positive value")
    d, c = holding.modified_duration, holding.convexity
    first = -d * dy
    second = first + 0.5 * c * dy * dy
    return HoldingImpact(
        name=holding.name,
        kind="fund",
        dy=dy,
        value0=holding.value,
        value1=holding.value * (1 + second),
        exact=None,
        duration_only=first,
        duration_convexity=second,
        modified_duration=d,
        convexity=c,
        dv01=holding.value * d * 1e-4,
        hold=None,
    )


@dataclass(frozen=True, slots=True)
class PortfolioImpact:
    holdings: tuple[HoldingImpact, ...]
    value0: float
    value1: float
    modified_duration: float
    """Value-weighted."""
    convexity: float
    dv01: float
    duration_only: float
    """Portfolio value change by duration alone (currency)."""
    duration_convexity: float

    @property
    def change(self) -> float:
        return self.value1 - self.value0


def portfolio_impact(
    bonds: Sequence[BondHolding],
    funds: Sequence[FundHolding],
    shocks: Sequence[float],
) -> PortfolioImpact:
    """Every holding repriced at its own yield change (bonds first, then funds, ``shocks`` in
    that order), and the totals.

    Equation:
        ΔV = Σᵢ ΔVᵢ;  D = Σᵢ wᵢ·Dᵢ,  C = Σᵢ wᵢ·Cᵢ,  wᵢ = Vᵢ/Σⱼ Vⱼ;  DV01 = Σᵢ DV01ᵢ
    """
    if len(shocks) != len(bonds) + len(funds):
        raise ValueError("one yield change per holding")
    impacts = [bond_impact(b, dy) for b, dy in zip(bonds, shocks, strict=False)]
    impacts += [fund_impact(f, dy) for f, dy in zip(funds, shocks[len(bonds) :], strict=True)]
    if not impacts:
        raise ValueError("the portfolio is empty")
    values: FloatArray = np.array([h.value0 for h in impacts])
    weights = values / values.sum()
    return PortfolioImpact(
        holdings=tuple(impacts),
        value0=float(values.sum()),
        value1=float(sum(h.value1 for h in impacts)),
        modified_duration=float(weights @ np.array([h.modified_duration for h in impacts])),
        convexity=float(weights @ np.array([h.convexity for h in impacts])),
        dv01=float(sum(h.dv01 for h in impacts)),
        duration_only=float(sum(h.duration_only * h.value0 for h in impacts)),
        duration_convexity=float(sum(h.duration_convexity * h.value0 for h in impacts)),
    )
