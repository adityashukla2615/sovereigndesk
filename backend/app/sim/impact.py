"""Module E: what the simulated shocks mean for a retail bond investor and a small business.

* The shock is read from the simulation, against the real data it was anchored to: the G-sec
  curve against FBIL's close, the 3-month T-bill and repo against RBI's and FBIL's prints, and
  the rupee against FBIL's reference rate once the linkage has moved it. So every shock in the
  other modules reaches it: a repo move, a CRR change, a Fed shock, a tax-day squeeze. A
  hypothetical move can be given instead (a parallel yield shift, a repo move, a rupee move).
* The portfolio and the two business profiles are ILLUSTRATIVE presets, editable in the panel:
  bonds are bought at about par at today's yields, funds carry a stated duration and convexity.
* An EBLR loan moves with repo one for one, by RBI's rule; an MCLR loan by the share and speed
  fitted on RBI's monthly 1-year median MCLR (from June 2022) against every repo decision.
"""

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.data.catalog import FBIL_GSEC_TENORS
from app.data.service import DataService
from app.sim.anchors import AnchorError, required_series
from app.sim.india_market import IndiaMarket
from sovereign_engine.impact import (
    BenchmarkFit,
    BondHolding,
    BusinessImpact,
    BusinessProfile,
    FundHolding,
    LoanTerms,
    MarketMove,
    PassThrough,
    business_impact,
    fit_benchmark,
    portfolio_impact,
)


@dataclass(frozen=True, slots=True)
class ImpactParams:
    """Settings that are assumptions or rules rather than fits (listed in ASSUMPTIONS.md)."""

    # VERIFY: "the interest rate under external benchmark shall be reset at least once in three
    # months", and banks raised their repo-linked benchmarks by the full 250 bp of May 2022 -
    # Feb 2023: RBI's external-benchmark circular of 4 Sep 2019 (as reported) and RBI Bulletin,
    # "Monetary Policy Transmission in India: Recent Dynamics" (16 Nov 2023). Checked 2026-10-21.
    eblr_per_repo: float = 1.0
    eblr_lag_months: int = 0
    mclr_per_money: float = 0.3
    """MCLR's share of the money market's move beyond repo (an assumption: banks' marginal cost
    of funds is mostly deposits, which reprice slowly, and partly CDs, which move at once)."""
    mclr_lag_months: float = 0.0
    months: int = 12
    """Months each business is followed for."""


@dataclass(frozen=True, slots=True)
class BondSpec:
    name: str
    face: float
    years: float
    spread_bp: float = 0.0
    """Over the G-sec curve; it is held unchanged by a shock."""


DEFAULT_BONDS: tuple[BondSpec, ...] = (
    BondSpec("1-year G-sec", 200_000, 1.0),
    BondSpec("5-year G-sec", 300_000, 5.0),
    BondSpec("10-year G-sec", 500_000, 10.0),
    BondSpec("30-year G-sec", 200_000, 30.0),
    BondSpec("AAA PSU bond, 3 years", 200_000, 3.0, 60.0),
)
DEFAULT_FUNDS: tuple[FundHolding, ...] = (
    FundHolding("Gilt fund", 300_000, modified_duration=7.5, convexity=80.0),
    FundHolding("Short-duration fund", 200_000, modified_duration=2.2, convexity=7.0),
)
PROFILES: dict[str, BusinessProfile] = {
    "SHOP": BusinessProfile(
        name="Small shop (groceries and household goods)",
        monthly_sales=600_000,
        cost_share=0.82,
        import_share=0.05,
        fx_to_price=0.5,
        inventory_days=20,
        rate_semi_elasticity=-0.3,
        price_elasticity=-0.5,
        loan=LoanTerms(1_000_000, "EBLR", 0.035, 3, 1, 12),
    ),
    "IMPORTER": BusinessProfile(
        name="Electronics retailer importing most of its stock",
        monthly_sales=15_000_000,
        cost_share=0.88,
        import_share=0.7,
        fx_to_price=0.6,
        inventory_days=60,
        rate_semi_elasticity=-2.0,
        price_elasticity=-1.2,
        loan=LoanTerms(20_000_000, "MCLR", 0.015, 12, 6, 12),
    ),
}
"""ILLUSTRATIVE: sizes, shares and elasticities are assumptions, not any firm's data."""


@dataclass(frozen=True, slots=True)
class ImpactModel:
    params: ImpactParams
    passthrough: PassThrough
    mclr_fit: BenchmarkFit
    mclr_now: float
    """The latest 1-year median MCLR (decimal)."""
    mclr_as_of: date
    mclr_sample: str


def _months(days: pd.DatetimeIndex) -> np.ndarray:
    """Dates as months since 2000 (fractional)."""
    return np.asarray(
        (days.year - 2000) * 12 + (days.month - 1) + (days.day - 1) / 30.0, dtype=np.float64
    )


def build_impact(service: DataService, params: ImpactParams | None = None) -> ImpactModel:
    """Fit the MCLR's response to repo on RBI's data and set the pass-through."""
    p = params or ImpactParams()
    mclr = required_series(service, "rbi/rates/mclr_1y").dropna().sort_index() / 100
    repo = required_series(service, "rbi/mpc/repo").dropna().sort_index() / 100
    if len(mclr) < 12:
        raise AnchorError(f"only {len(mclr)} months of MCLR on record")
    changes = repo.diff().dropna()
    changes = changes[changes != 0]
    observed = pd.DatetimeIndex(mclr.index) + pd.Timedelta(days=14)  # the month's middle
    fit = fit_benchmark(
        _months(observed),
        mclr.to_numpy(),
        _months(pd.DatetimeIndex(changes.index)),
        changes.to_numpy(),
        lag_months=p.mclr_lag_months,
    )
    passthrough = PassThrough(
        eblr_per_repo=p.eblr_per_repo,
        eblr_lag_months=p.eblr_lag_months,
        mclr_per_repo=fit.share,
        mclr_per_money=p.mclr_per_money,
        mclr_months=fit.months,
        mclr_lag_months=math.ceil(p.mclr_lag_months),
    )
    days = pd.DatetimeIndex(mclr.index)
    return ImpactModel(
        params=p,
        passthrough=passthrough,
        mclr_fit=fit,
        mclr_now=float(mclr.iloc[-1]),
        mclr_as_of=days[-1].date(),
        mclr_sample=f"monthly, {days[0]:%b %Y}–{days[-1]:%b %Y}",
    )


# ----------------------------------------------------------------------- the shock


def _interpolate(curve: dict[str, float], years: float) -> float:
    xs = np.array([FBIL_GSEC_TENORS[t] for t in curve])
    ys = np.array(list(curve.values()))
    order = np.argsort(xs)
    return float(np.interp(years, xs[order], ys[order]))


@dataclass(frozen=True, slots=True)
class Shock:
    """The moves the impact is computed for."""

    source: str
    """"simulation" or "hypothetical"."""
    base: dict[str, float]
    """The G-sec curve before the shock: FBIL's close."""
    now: dict[str, float]
    move: MarketMove
    inr_base: float | None
    inr_now: float | None
    notes: list[str] = field(default_factory=list)

    def dy(self, years: float) -> float:
        return _interpolate(self.now, years) - _interpolate(self.base, years)


def read_shock(
    india: IndiaMarket,
    *,
    inr_base: float | None,
    shift_bp: float | None = None,
    repo_bp: float | None = None,
    inr_pct: float | None = None,
) -> Shock:
    """The simulation's moves since its anchors, or a hypothetical move where one is given."""
    a = india.anchors
    if india.gsec is None or a.gsec is None:
        raise AnchorError("the impact needs the G-sec curve, which is unavailable")
    base = dict(a.gsec.close)
    beta = india.tbill_beta["3M"]
    hypothetical = any(v is not None for v in (shift_bp, repo_bp, inr_pct))
    if not hypothetical:
        inr_now = india.inr
        move = MarketMove(
            repo=india.repo - a.repo,
            money=india.tbills()["3M"] - a.tbills["3M"],
            money_beta=beta,
            inr_pct=(inr_now / inr_base - 1) * 100 if inr_now and inr_base else 0.0,
        )
        return Shock("simulation", base, dict(india.gsec.points), move, inr_base, inr_now)
    shift = (shift_bp or 0.0) / 1e4
    repo = (repo_bp or 0.0) / 1e4
    # A repo move reaches the curve as the G-sec curve passes one through: by its β(τ).
    now = {t: y + shift + india.gsec.betas.get(t, 1.0) * repo for t, y in base.items()}
    move = MarketMove(repo=repo, money=beta * repo, money_beta=beta, inr_pct=inr_pct or 0.0)
    inr_now = None if inr_base is None else inr_base * (1 + move.inr_pct / 100)
    notes = []
    if shift_bp is not None and repo_bp is None:
        notes.append("a parallel yield shift for the portfolio; lending rates unchanged")
    return Shock("hypothetical", base, now, move, inr_base, inr_now, notes)


# ----------------------------------------------------------------------- the panel


def bonds_at_par(specs: tuple[BondSpec, ...], shock: Shock) -> list[BondHolding]:
    """The preset bonds, each with a coupon at today's yield for its maturity (about par)."""
    out = []
    for s in specs:
        y0 = _interpolate(shock.base, s.years) + s.spread_bp / 1e4
        out.append(BondHolding(s.name, s.face, round(y0, 4), s.years, y0))
    return out


def market_bond(
    name: str, face: float, coupon: float, years: float, spread_bp: float, shock: Shock
) -> BondHolding:
    """A bond the user holds, priced at today's yield for its maturity plus its spread."""
    y0 = _interpolate(shock.base, years) + spread_bp / 1e4
    return BondHolding(name, face, coupon, years, y0)


def _holding_row(h: Any, spec: BondHolding | FundHolding, shock: Shock) -> dict[str, Any]:
    bond = spec if isinstance(spec, BondHolding) else None
    hold = None
    if h.hold is not None:
        hold = {
            "coupons": h.hold.coupons,
            "redemption": h.hold.redemption,
            "payments": len(h.hold.schedule),
            "bought_yield": h.hold.bought_yield,
            "realised_yield": h.hold.realised_yield,
            "sale_proceeds": h.hold.sale_proceeds,
            "sale_gain": h.hold.sale_gain,
        }
    return {
        "name": h.name,
        "kind": h.kind,
        "years": None if bond is None else bond.years,
        "coupon": None if bond is None else bond.coupon,
        "face": None if bond is None else bond.face,
        "base_yield": None if bond is None else bond.yield0,
        "spread_bp": None
        if bond is None
        else (bond.yield0 - _interpolate(shock.base, bond.years)) * 1e4,
        "dy_bp": h.dy * 1e4,
        "value0": h.value0,
        "value1": h.value1,
        "change": h.change,
        "exact_pct": None if h.exact is None else h.exact * 100,
        "duration_pct": h.duration_only * 100,
        "convexity_pct": h.duration_convexity * 100,
        "modified_duration": h.modified_duration,
        "convexity": h.convexity,
        "dv01": h.dv01,
        "hold": hold,
    }


def _business_row(key: str, impact: BusinessImpact) -> dict[str, Any]:
    p, loan = impact.profile, impact.profile.loan
    last = -1
    return {
        "key": key,
        "name": p.name,
        "profile": {
            "monthly_sales": p.monthly_sales,
            "cost_share": p.cost_share,
            "import_share": p.import_share,
            "fx_to_price": p.fx_to_price,
            "inventory_days": p.inventory_days,
            "rate_semi_elasticity": p.rate_semi_elasticity,
            "price_elasticity": p.price_elasticity,
            "loan": {
                "amount": loan.amount,
                "benchmark": loan.benchmark,
                "spread": loan.spread,
                "reset_months": loan.reset_months,
                "first_reset_month": loan.first_reset_month,
                "tenor_months": loan.tenor_months,
            },
        },
        "base_rate": impact.base_rate,
        "base_interest": impact.base_interest,
        "base_margin": impact.base_margin,
        "months": list(range(1, impact.margin.size + 1)),
        "loan_rate_bp": (impact.loan_rate * 1e4).tolist(),
        "interest": impact.interest.tolist(),
        "import_cost": impact.import_cost.tolist(),
        "price_pct": impact.price_pct.tolist(),
        "volume_pct": impact.volume_pct.tolist(),
        "sales": impact.sales.tolist(),
        "margin": impact.margin.tolist(),
        "summary": {
            "loan_rate_bp": float(impact.loan_rate[last] * 1e4),
            "interest": float(impact.interest[last]),
            "margin": float(impact.margin[last]),
            "margin_pct": float(impact.margin[last] / impact.base_margin * 100)
            if impact.base_margin
            else None,
            "sales_pct": float(impact.sales[last] / p.monthly_sales * 100),
            "year_margin": float(impact.margin.sum()),
        },
    }


def impact_panel(
    model: ImpactModel,
    india: IndiaMarket,
    shock: Shock,
    *,
    bonds: list[BondHolding] | None = None,
    funds: list[FundHolding] | None = None,
    profiles: dict[str, BusinessProfile] | None = None,
) -> dict[str, Any]:
    """Both views for one shock: the portfolio repriced and each business month by month."""
    holdings = bonds if bonds is not None else bonds_at_par(DEFAULT_BONDS, shock)
    fund_list = funds if funds is not None else list(DEFAULT_FUNDS)
    shocks = [shock.dy(b.years) for b in holdings] + [
        shock.dy(f.modified_duration) for f in fund_list
    ]
    portfolio = portfolio_impact(holdings, fund_list, shocks) if shocks else None
    rows = []
    if portfolio is not None:
        specs: list[BondHolding | FundHolding] = [*holdings, *fund_list]
        rows = [
            _holding_row(h, spec, shock) for h, spec in zip(portfolio.holdings, specs, strict=True)
        ]
    benchmarks = {"EBLR": india.anchors.repo, "MCLR": model.mclr_now}  # before the shock
    business = [
        _business_row(
            key,
            business_impact(
                profile,
                shock.move,
                model.passthrough,
                base_benchmark=benchmarks[profile.loan.benchmark],
                months=model.params.months,
            ),
        )
        for key, profile in (profiles if profiles is not None else PROFILES).items()
    ]
    curve = [
        {
            "tenor": t,
            "years": FBIL_GSEC_TENORS[t],
            "base": shock.base[t],
            "now": shock.now.get(t, shock.base[t]),
            "change_bp": (shock.now.get(t, shock.base[t]) - shock.base[t]) * 1e4,
        }
        for t in FBIL_GSEC_TENORS
        if t in shock.base
    ]
    fit, pt = model.mclr_fit, model.passthrough
    m = shock.move
    return {
        "illustrative": True,
        "shock": {
            "source": shock.source,
            "notes": shock.notes,
            "as_of": india.anchors.gsec.as_of.isoformat() if india.anchors.gsec else None,
            "curve": curve,
            "repo_bp": m.repo * 1e4,
            "money_bp": m.money * 1e4,
            "liquidity_bp": (m.money - m.money_beta * m.repo) * 1e4,
            "inr_pct": m.inr_pct,
            "inr_base": shock.inr_base,
            "inr_now": shock.inr_now,
        },
        "retail": {
            "holdings": rows,
            "totals": None
            if portfolio is None
            else {
                "value0": portfolio.value0,
                "value1": portfolio.value1,
                "change": portfolio.change,
                "change_pct": portfolio.change / portfolio.value0 * 100,
                "duration_only": portfolio.duration_only,
                "duration_convexity": portfolio.duration_convexity,
                "modified_duration": portfolio.modified_duration,
                "convexity": portfolio.convexity,
                "dv01": portfolio.dv01,
            },
        },
        "business": business,
        "passthrough": {
            "eblr_per_repo": pt.eblr_per_repo,
            "eblr_lag_months": pt.eblr_lag_months,
            "mclr_per_repo": pt.mclr_per_repo,
            "mclr_months": pt.mclr_months,
            "mclr_per_money": pt.mclr_per_money,
            "mclr_fit": {
                "share": fit.share,
                "months": fit.months,
                "rmse_bp": fit.rmse * 1e4,
                "n": fit.n,
                "sample": model.mclr_sample,
            },
            "mclr_now": model.mclr_now,
            "mclr_as_of": model.mclr_as_of.isoformat(),
            "repo_base": india.anchors.repo,
        },
    }
