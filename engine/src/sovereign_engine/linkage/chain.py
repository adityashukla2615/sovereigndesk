"""US → India transmission (Module C): one US shock followed day by day.

    Fed move → US 10Y → IN−US 10Y differential → FPI flows → RBI's dollar sales and the
    rupee → rupee liquidity → WACR and T-bills → RBI's response

* The US 10Y move is an input: the US simulator's own response to the Fed move.
* India's 10Y follows by the spillover β, so the differential changes by (β − 1)·ΔUS10Y.
* FPI flows over the next month respond to the change in the differential (debt), to the US
  10Y (equity) and to the VIX: a portfolio adjustment, arriving front-loaded over the month.
* RBI absorbs a share s of each day's flow in its reserves: it sells dollars as they leave and
  buys as they come. The rest of the flow moves the rupee.
* RBI's dollar sales take rupees out of the banking system one for one: the drain in ₹ crore
  is the dollars sold times the day's rate (dollar purchases inject the same way).
* India's money market responds through the liquidity map (WACR − repo against surplus as % of
  NDTL) and the T-bill's slope on liquidity. Surplus is RBI's net liquidity position, as in its
  releases and the map's fit: net absorption through the LAF, VRR and VRRR included.
* RBI's response, from the next day:
  - let rates move;
  - weekly VRR auctions (VRRR after inflows) of the drain so far: they fund the shortfall at the
    repo rate rather than the MSF, but leave the net position, and so the map, where it was;
  - weekly outright OMO purchases (sales) of the drain not yet offset, which restore it;
  - a buy/sell swap: RBI buys back, spot, the dollars it expects to sell, injecting rupees;
  - a repo hike, which widens the differential again and slows the outflow.

Flows are US$ billion (negative: out of India), rates per cent unless named decimal, liquidity
₹ crore (surplus positive: RBI absorbing on net). The chain is linear in the shock.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np

from sovereign_engine._types import FloatArray
from sovereign_engine.india.liquidity_map import LiquidityMap

Response = Literal["none", "vrr", "omo", "swap", "hike"]
RESPONSES: tuple[Response, ...] = ("none", "vrr", "omo", "swap", "hike")


@dataclass(frozen=True, slots=True)
class LinkParams:
    spillover: float
    """ΔIN 10Y per ΔUS 10Y on the day."""
    debt_flow: float
    """FPI debt flows over the month (US$ bn) per percentage point change in the IN−US 10Y
    differential."""
    equity_flow: float
    """FPI equity flows over the month (US$ bn) per percentage point change in the US 10Y."""
    risk_flow: float
    """FPI flows over the month (US$ bn) per point change in the VIX."""
    intervention: float
    """Share of each day's FPI flow RBI absorbs in its reserves (0–1)."""
    inr_per_bn: float
    """Rupee depreciation (%) per US$ bn of outflow RBI does not absorb."""
    flow_days: int = 21
    """Business days over which a month's flow arrives."""
    half_life_days: float = 5.0
    """Half-life of the flow's daily profile."""
    response_lag_days: int = 1
    """RBI responds from this business day on."""
    omo_every_days: int = 5
    """Business days between RBI's VRR auctions or OMO purchases (weekly)."""
    hike_bp: float = 25.0
    """The repo move of the hike response."""
    hike_10y: float = 0.54
    """India's 10Y move per unit of repo surprise (the G-sec event study's β at 10 years)."""
    hike_3m: float = 1.0
    """The 3-month T-bill's move per unit of repo surprise."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.intervention <= 1.0:
            raise ValueError("intervention is a share between 0 and 1")
        if self.flow_days < 1 or self.half_life_days <= 0:
            raise ValueError("need flow_days ≥ 1 and half_life_days > 0")

    def profile(self) -> FloatArray:
        """The share of a month's flow arriving on each business day, front-loaded.

        Equation:
            w_k = 2^(−k/h) / Σ_{j=0}^{N−1} 2^(−j/h),   k = 0 … N−1
        """
        w = 2.0 ** (-np.arange(self.flow_days) / self.half_life_days)
        return np.asarray(w / w.sum(), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class FedShock:
    fed_bp: float
    """The Fed's move (basis points)."""
    us10y_bp: float
    """The US 10Y's response (basis points)."""
    vix: float = 0.0
    """The VIX's change (points): a risk-off shock that comes with the move, if any."""


@dataclass(frozen=True, slots=True)
class MarketStart:
    inr: float
    """Rupees per dollar."""
    reserves_bn: float
    """RBI's foreign exchange reserves (US$ bn)."""
    surplus_cr: float
    """System liquidity surplus (₹ crore; negative: deficit)."""
    ndtl_cr: float
    repo: float
    """Decimal."""


@dataclass(frozen=True, slots=True)
class ChainPath:
    """Each node of the chain on each business day from the shock (day 0)."""

    shock: FedShock
    response: Response
    params: LinkParams
    start: MarketStart
    in10y_bp: FloatArray
    """India's 10Y change since the shock."""
    differential_bp: FloatArray
    """The IN−US 10Y differential's change since the shock."""
    fpi_bn: FloatArray
    """FPI net flow each day."""
    rbi_bn: FloatArray
    """RBI's net dollar purchases from the flow each day (negative: sales)."""
    market_bn: FloatArray
    """The part of the flow the market absorbs, which moves the rupee."""
    swap_bn: FloatArray
    """Dollars RBI buys spot in a buy/sell swap."""
    inr: FloatArray
    reserves_bn: FloatArray
    drain_cr: FloatArray
    """Rupee liquidity from RBI's dollar trades each day (negative: drained)."""
    injection_cr: FloatArray
    """Durable rupee liquidity from RBI's response each day (OMOs, the swap)."""
    vrr_cr: FloatArray
    """VRR (positive) or VRRR (negative) auctioned each day: the amount outstanding from then
    to the next auction. It does not change the net position."""
    surplus_cr: FloatArray
    repo_bp: FloatArray
    """The repo rate's change since the shock."""
    wacr_bp: FloatArray
    """WACR's change since the shock, from the liquidity map and the repo."""
    tbill_bp: FloatArray
    """The 3-month T-bill's change since the shock."""

    @property
    def days(self) -> int:
        return int(self.fpi_bn.size)

    def totals(self) -> dict[str, float]:
        """Each node's cumulative change over the horizon.

        Equation:
            F = Σ fₜ,  R = Σ rₜ,  M = Σ mₜ,  D = Σ dₜ,  I = Σ iₜ,  V = the last VRR auctioned,
            ΔX = X_T − X₀,  ΔRes = Res_T − Res₀,  ΔS = S_T − S₀
        """
        return {
            "fed_bp": self.shock.fed_bp,
            "us10y_bp": self.shock.us10y_bp,
            "in10y_bp": float(self.in10y_bp[-1]),
            "differential_bp": float(self.differential_bp[-1]),
            "fpi_bn": float(self.fpi_bn.sum()),
            "rbi_bn": float(self.rbi_bn.sum()),
            "market_bn": float(self.market_bn.sum()),
            "swap_bn": float(self.swap_bn.sum()),
            "inr": float(self.inr[-1]),
            "inr_pct": float((self.inr[-1] / self.start.inr - 1) * 100),
            "reserves_bn": float(self.reserves_bn[-1] - self.start.reserves_bn),
            "drain_cr": float(self.drain_cr.sum()),
            "injection_cr": float(self.injection_cr.sum()),
            "vrr_cr": float(self.vrr_cr[self.vrr_cr != 0][-1]) if self.vrr_cr.any() else 0.0,
            "surplus_cr": float(self.surplus_cr[-1] - self.start.surplus_cr),
            "surplus_pct": float(self.surplus_cr[-1] - self.start.surplus_cr)
            / self.start.ndtl_cr
            * 100,
            "repo_bp": float(self.repo_bp[-1]),
            "wacr_bp": float(self.wacr_bp[-1]),
            "tbill_bp": float(self.tbill_bp[-1]),
        }

    def check(self, tol: float = 1e-6) -> list[str]:
        """The chain's accounting identities, each as a message if it fails (empty: all hold).

        Equation:
            fₜ = rₜ + mₜ;   Resₜ = Res₀ + Σ_{u≤t}(r_u + swap_u);   dₜ = 100·rₜ·Xₜ (₹ crore);
            Sₜ = S₀ + Σ_{u≤t}(d_u + i_u)   (a swap's rupees, 100·swapₜ·Xₜ, are part of iₜ)
        """
        problems = []
        if not np.allclose(self.fpi_bn, self.rbi_bn + self.market_bn, atol=tol):
            problems.append("FPI flows ≠ RBI's purchases + the market's")
        reserves = self.start.reserves_bn + np.cumsum(self.rbi_bn + self.swap_bn)
        if not np.allclose(self.reserves_bn, reserves, atol=tol):
            problems.append("reserves ≠ start + RBI's purchases + swaps")
        if not np.allclose(self.drain_cr, 100.0 * self.rbi_bn * self.inr, rtol=1e-9, atol=tol):
            problems.append("rupee liquidity ≠ dollars bought or sold × the day's rate")
        surplus = self.start.surplus_cr + np.cumsum(self.drain_cr + self.injection_cr)
        if not np.allclose(self.surplus_cr, surplus, rtol=1e-12, atol=1e-3):
            problems.append("surplus ≠ start + drains + injections")
        return problems


def run_chain(
    shock: FedShock,
    start: MarketStart,
    params: LinkParams,
    *,
    response: Response = "none",
    horizon_days: int = 30,
    liquidity_map: LiquidityMap | None = None,
    tbill_slope_bp: float = 0.0,
) -> ChainPath:
    """Follow one US shock through India's markets for ``horizon_days`` business days.

    Equation:
        Δd = (β − 1)·ΔUS10Y + κ₁₀·Δrepo;   F = a_d·Δd + a_e·ΔUS10Y + a_v·ΔVIX   (pp, US$ bn)
        fₜ = F·wₜ (+ the hike's own flow from its day);  rₜ = s·fₜ;  mₜ = fₜ − rₜ
        Xₜ = Xₜ₋₁·(1 − e·mₜ/100);  Resₜ = Resₜ₋₁ + rₜ + swapₜ;  dₜ = 100·rₜ·Xₜ
        Sₜ = Sₜ₋₁ + dₜ + iₜ;   ΔWACRₜ = map(Sₜ/NDTL) − map(S₀/NDTL) + Δrepoₜ;
        ΔTBₜ = b·(Sₜ − S₀)/NDTL·100 + κ₃·Δrepoₜ
    """
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    if response not in RESPONSES:
        raise ValueError(f"response must be one of {RESPONSES}")
    p, n = params, horizon_days
    w = p.profile()
    lag = min(p.response_lag_days, n - 1)

    def arrival(total: float, first: int) -> FloatArray:
        out = np.zeros(n)
        k = min(p.flow_days, n - first)
        if k > 0:
            out[first : first + k] = total * w[:k]
        return out

    repo_bp = np.zeros(n)
    if response == "hike":
        repo_bp[lag:] = p.hike_bp
    in10y = np.full(n, p.spillover * shock.us10y_bp) + p.hike_10y * repo_bp
    differential = in10y - shock.us10y_bp
    flow = (
        p.debt_flow * (p.spillover - 1.0) * shock.us10y_bp / 100
        + p.equity_flow * shock.us10y_bp / 100
        + p.risk_flow * shock.vix
    )
    fpi = arrival(flow, 0)
    if response == "hike":
        fpi += arrival(p.debt_flow * p.hike_10y * p.hike_bp / 100, lag)
    rbi = p.intervention * fpi
    market = fpi - rbi
    swap = np.zeros(n)
    if response == "swap":
        swap[lag] = -rbi.sum()  # buy back, spot, the dollars RBI expects to sell
    inr = start.inr * np.cumprod(1.0 - p.inr_per_bn * market / 100)
    reserves = start.reserves_bn + np.cumsum(rbi + swap)
    drain = 100.0 * rbi * inr
    injection = 100.0 * swap * inr
    vrr = np.zeros(n)
    if response == "vrr":  # weekly auctions of the whole drain so far, maturing at the next
        for day in range(lag, n, p.omo_every_days):
            vrr[day] = -float(drain[:day].sum())
    elif response == "omo":  # weekly outright purchases of the drain not yet offset
        done = 0.0
        for day in range(lag, n, p.omo_every_days):
            owed = -float(drain[:day].sum()) - done
            injection[day] = owed
            done += owed
    surplus = start.surplus_cr + np.cumsum(drain + injection)
    level = surplus / start.ndtl_cr * 100
    level_0 = start.surplus_cr / start.ndtl_cr * 100
    if liquidity_map is not None:
        base = float(liquidity_map.spread(level_0))
        wacr = (np.asarray(liquidity_map.spread(level)) - base) * 1e4 + repo_bp
    else:
        wacr = repo_bp.copy()
    tbill = tbill_slope_bp * (level - level_0) + p.hike_3m * repo_bp
    return ChainPath(
        shock=shock,
        response=response,
        params=p,
        start=start,
        in10y_bp=in10y,
        differential_bp=differential,
        fpi_bn=fpi,
        rbi_bn=rbi,
        market_bn=market,
        swap_bn=swap,
        inr=inr,
        reserves_bn=reserves,
        drain_cr=drain,
        injection_cr=injection,
        vrr_cr=vrr,
        surplus_cr=surplus,
        repo_bp=repo_bp,
        wacr_bp=wacr,
        tbill_bp=tbill,
    )


@dataclass(frozen=True, slots=True)
class ChainReplay:
    """The chain driven by actual daily moves, day by day."""

    in10y_bp: FloatArray
    """India's 10Y change since the start, from the spillover."""
    fpi_bn: FloatArray
    """FPI net flow each day."""
    rbi_bn: FloatArray
    market_bn: FloatArray
    inr: FloatArray
    reserves_bn: FloatArray


def replay_chain(
    us10y_bp: FloatArray, vix: FloatArray, start: MarketStart, params: LinkParams
) -> ChainReplay:
    """Run the chain on a sequence of daily moves (the US 10Y's and the VIX's changes): each
    day's move starts its own month of flows, and the months overlap.

    Equation:
        Fₜ = a_d·(β − 1)·ΔUS10Yₜ/100 + a_e·ΔUS10Yₜ/100 + a_v·ΔVIXₜ;   fₜ = Σ_{k≥0} F_{t−k}·w_k
        rₜ = s·fₜ;  mₜ = fₜ − rₜ;  Xₜ = Xₜ₋₁·(1 − e·mₜ/100);  Resₜ = Resₜ₋₁ + rₜ;
        ΔIN10Yₜ = β·Σ_{u≤t} ΔUS10Y_u
    """
    us = np.nan_to_num(np.asarray(us10y_bp, dtype=np.float64))
    risk = np.nan_to_num(np.asarray(vix, dtype=np.float64))
    if us.shape != risk.shape or us.ndim != 1:
        raise ValueError("one US 10Y change and one VIX change per day")
    p = params
    impulses = (
        p.debt_flow * (p.spillover - 1.0) * us / 100 + p.equity_flow * us / 100 + p.risk_flow * risk
    )
    fpi = np.convolve(impulses, p.profile())[: us.size]
    rbi = p.intervention * fpi
    market = fpi - rbi
    inr = start.inr * np.cumprod(1.0 - p.inr_per_bn * market / 100)
    return ChainReplay(
        in10y_bp=p.spillover * np.cumsum(us),
        fpi_bn=fpi,
        rbi_bn=rbi,
        market_bn=market,
        inr=inr,
        reserves_bn=start.reserves_bn + np.cumsum(rbi),
    )
