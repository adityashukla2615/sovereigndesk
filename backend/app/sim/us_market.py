"""The simulated US Treasury and funding market.

State evolves on every tick from real anchors:

* the curve: today's fitted NSS curve moved by a Hull–White short-rate factor x (loading
  B(τ)/τ), plus deviation layers that survive re-anchoring (policy moves, the term premium
  including QT, price impact of sales). The curve is evaluated at t = 0 on purpose: the
  risk-neutral roll toward the forwards would make it drift up for no reason, whereas here it
  moves only on shocks and noise, and x mean-reverts back to the anchored curve;
* EFFR: a logit-OU process around IORB plus the fitted reserve-demand spread, so it can never
  leave the target range;
* the Fed balance sheet: QT runoff drains ON RRP first, then reserves, and the identity holds.

Displayed par yields add a fixed fit correction so that the opening print equals the official
par curve exactly. Every parameter not fitted to data is listed in ASSUMPTIONS.md.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from app.sim.anchors import TENOR_YEARS, USAnchors
from sovereign_engine._types import FloatArray
from sovereign_engine.bonds.approx import price_yield_profile
from sovereign_engine.bonds.cashflows import CashFlows, risk_measures
from sovereign_engine.rates.corridor import corridor_ou_step, logit_sigma_for
from sovereign_engine.rates.hull_white import HullWhite
from sovereign_engine.rates.loadings import expectations_loading, term_premium_loading
from sovereign_engine.us.balance_sheet import (
    AVERAGE_MONTH_DAYS,
    FedBalanceSheet,
    QTPlan,
    term_premium_effect,
)
from sovereign_engine.us.corridor import FedCorridor, effr_target
from sovereign_engine.us.debt import DebtPath, project_debt_service
from sovereign_engine.us.impact import PriceImpactModel, split_sale

YEAR_DAYS = 365.25
DISPLAY_TENORS: tuple[str, ...] = (
    "1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y",
)  # fmt: skip
COUPON_TENORS: tuple[str, ...] = tuple(t for t in DISPLAY_TENORS if TENOR_YEARS[t] >= 1)
EVAL_TENORS: FloatArray = np.array(sorted({1 / 12, 0.25, *(np.arange(1, 61) / 2)}))
"""Maturities the model curve is evaluated on: bill points plus the semiannual coupon grid."""


@dataclass(frozen=True, slots=True)
class USModelParams:
    """Parameters that are assumptions rather than fits (listed in ASSUMPTIONS.md)."""

    hw_a: float = 0.10
    hw_sigma: float = 0.0085
    tp_kappa: float = 1.0
    tp_sigma: float = 0.006
    effr_kappa: float = 250.0
    effr_rate_vol: float = 0.0010
    policy_passthrough: float = 0.5
    """κ_p in the hike loading (1 − e^(−κ_p·τ))/(κ_p·τ): ≈1 at the front end, 0.2 at 10 years."""
    tp_scale_years: float = 7.0
    mbs_duration: float = 5.5
    dollar_pct_per_100bn: float = -0.25
    """UNCALIBRATED: broad dollar move per $100bn of Treasuries sold by foreign holders."""
    reserves_floor: float = 0.0


@dataclass(slots=True)
class SaleOrder:
    country: str
    total: float
    days: float
    mix: dict[str, float]
    """Share of the sale in each tenor bucket."""
    sold: float = 0.0

    @property
    def pace(self) -> float:
        return self.total / self.days

    @property
    def done(self) -> bool:
        return self.sold >= self.total - 1e-9


@dataclass(frozen=True, slots=True)
class PriceYieldPanel:
    tenor: str
    ytm: float
    price: float
    macaulay: float
    modified: float
    convexity: float
    dv01: float
    shifts_bp: list[float]
    exact: list[float]
    duration_only: list[float]
    duration_convexity: list[float]


@dataclass(frozen=True, slots=True)
class QTProjection:
    monthly_total: float
    reserves: list[float]
    effr_iorb_spread: list[float]
    ten_year_term_premium_change: list[float]


@dataclass(frozen=True, slots=True)
class DebtComparison:
    start: str
    months: list[str]
    baseline_interest: list[float]
    shocked_interest: list[float]
    baseline_to_gdp: list[float]
    shocked_to_gdp: list[float]
    baseline_to_receipts: list[float]
    shocked_to_receipts: list[float]
    delta_by_year: dict[str, float]


@dataclass(slots=True)
class USState:
    corridor: FedCorridor
    sheet: FedBalanceSheet
    effr: float
    qt: QTPlan
    holdings: dict[str, float]
    t: float = 0.0
    """Simulated years since the current anchors were taken."""
    x: float = 0.0
    tp_dev: float = 0.0
    qt_10ye: float = 0.0
    """10-year equivalents the public has absorbed because of QT (USD bn)."""
    policy_shift: float = 0.0
    sold: dict[str, float] = field(default_factory=dict)
    temp: FloatArray = field(default_factory=lambda: np.zeros(EVAL_TENORS.size))
    orders: list[SaleOrder] = field(default_factory=list)
    dollar_shift_pct: float = 0.0
    qt_halted: bool = False


def par_from_zero(zeros: FloatArray) -> dict[str, float]:
    """Bond-equivalent par yields at the display tenors from zero rates on ``EVAL_TENORS``."""
    discount = np.exp(-zeros * EVAL_TENORS)
    dfs = discount[EVAL_TENORS >= 0.5]
    annuity = np.cumsum(dfs)
    out: dict[str, float] = {}
    for tenor in DISPLAY_TENORS:
        years = TENOR_YEARS[tenor]
        if years < 0.5:
            i = int(np.argmin(np.abs(EVAL_TENORS - years)))
            out[tenor] = float((1 / discount[i] - 1) / years)  # money-market (simple) yield
        else:
            n = round(years * 2)
            out[tenor] = float(2 * (1 - dfs[n - 1]) / annuity[n - 1])
    return out


def par_duration(y: float, years: float) -> float:
    """Modified duration of a semiannual par bond, or of a bill held to maturity."""
    if years < 1:
        return years / (1 + y * years)
    return (1 - (1 + y / 2) ** (-2 * years)) / y if y > 0 else years


_DISPLAY_YEARS = np.array([TENOR_YEARS[k] for k in DISPLAY_TENORS])


def interp_par(par: dict[str, float], tenor: float) -> float:
    return float(np.interp(tenor, _DISPLAY_YEARS, [par[k] for k in DISPLAY_TENORS]))


class USMarket:
    def __init__(
        self, anchors: USAnchors, rng: np.random.Generator, params: USModelParams | None = None
    ) -> None:
        self.params = params or USModelParams()
        self.rng = rng
        self.state = USState(
            corridor=anchors.corridor,
            sheet=anchors.balance_sheet,
            effr=anchors.effr,
            qt=anchors.observed_qt,
            holdings=dict(anchors.foreign_holdings),
        )
        self.impact = PriceImpactModel(reference_market=anchors.debt_public_2010)
        self.anchors = anchors
        self.hw = HullWhite(self.params.hw_a, self.params.hw_sigma, anchors.zero_curve)
        self.fit_correction = self._fit_correction()

    def _fit_correction(self) -> dict[str, float]:
        """Cache the anchored curve and its loadings, and return official minus model par yields.

        At t = 0 Hull–White gives ln P(0, τ) = ln P^M(0, τ) − B(0, τ)·x, so the zero curve is
        the anchored curve plus x·B(τ)/τ: both terms are fixed until the next re-anchor.
        """
        p = self.params
        self._base_zero = self.anchors.zero_curve.zero_rate(EVAL_TENORS)
        self._x_loading = self.hw.loading(0.0, EVAL_TENORS) / EVAL_TENORS
        self._tp_loading = term_premium_loading(EVAL_TENORS, p.tp_scale_years)
        self._policy_loading = expectations_loading(EVAL_TENORS, p.policy_passthrough)
        base = par_from_zero(self._base_zero)
        return {k: self.anchors.par_curve[k] - v for k, v in base.items()}

    def reanchor(self, anchors: USAnchors) -> None:
        """New real data: rebuild the base curve; every shock and policy layer is kept."""
        self.anchors = anchors
        self.hw = HullWhite(self.params.hw_a, self.params.hw_sigma, anchors.zero_curve)
        self.state.t = 0.0
        self.fit_correction = self._fit_correction()

    # ------------------------------------------------------------------ curve

    @property
    def market_size(self) -> float:
        return self.anchors.debt_public

    def qt_term_premium(self) -> float:
        return term_premium_effect(self.state.qt_10ye, self.anchors.nominal_gdp)

    def _deviation(self) -> FloatArray:
        s = self.state
        tp = (s.tp_dev + self.qt_term_premium()) * self._tp_loading
        policy = s.policy_shift * self._policy_loading
        impact = self.impact.permanent(s.sold, self.market_size, EVAL_TENORS) + s.temp
        return tp + policy + impact

    def _zeros(self) -> FloatArray:
        return self._base_zero + self.state.x * self._x_loading + self._deviation()

    def par_curve(self) -> dict[str, float]:
        raw = par_from_zero(self._zeros())
        return {k: v + self.fit_correction[k] for k, v in raw.items()}

    # ------------------------------------------------------------------ dynamics

    def reserves_ratio(self) -> float:
        return self.state.sheet.reserves / self.anchors.bank_assets

    def effr_target(self) -> float:
        corridor = self.state.corridor
        target = effr_target(corridor, self.anchors.reserve_curve, self.reserves_ratio())
        inset = 1e-6  # the logit-OU needs a target strictly inside the range
        return min(max(target, corridor.lower + inset), corridor.upper - inset)

    def _runoff(
        self, sheet: FedBalanceSheet, treasuries: float, mbs: float
    ) -> tuple[float, float, bool]:
        """Scale runoff down if it would push reserves below their floor."""
        room = sheet.reserves + sheet.on_rrp - self.params.reserves_floor
        if treasuries + mbs <= room:
            return treasuries, mbs, False
        scale = max(room, 0.0) / (treasuries + mbs)
        return treasuries * scale, mbs * scale, True

    def step(self, dt_years: float) -> list[str]:
        """Advance the market by ``dt_years``; returns plain-language notices (e.g. QT halted)."""
        p, s = self.params, self.state
        notices: list[str] = []
        days = dt_years * YEAR_DAYS
        s.t += dt_years
        s.x = float(self.hw.step_x(s.x, dt_years, self.rng))
        decay = math.exp(-p.tp_kappa * dt_years)
        tp_sd = p.tp_sigma * math.sqrt(-math.expm1(-2 * p.tp_kappa * dt_years) / (2 * p.tp_kappa))
        s.tp_dev = s.tp_dev * decay + tp_sd * float(self.rng.standard_normal())

        if not s.qt_halted and s.qt.treasury_cap + s.qt.mbs_cap > 0:
            treasuries, mbs, halted = self._runoff(s.sheet, *s.qt.runoff(days))
            if halted:
                s.qt_halted = True
                notices.append("QT halted: further runoff would push reserves below their floor")
            s.sheet = s.sheet.run_off(treasuries, mbs)
            par = self.par_curve()
            s.qt_10ye += treasuries * self.treasury_10ye_ratio(par) + mbs * self.mbs_10ye_ratio(par)

        pace: dict[str, float] = {}
        for order in s.orders:
            amount = min(order.pace * days, order.total - order.sold)
            order.sold += amount
            s.holdings[order.country] = s.holdings.get(order.country, 0.0) - amount
            s.dollar_shift_pct += p.dollar_pct_per_100bn * amount / 100
            for bucket, share in order.mix.items():
                s.sold[bucket] = s.sold.get(bucket, 0.0) + amount * share
                pace[bucket] = pace.get(bucket, 0.0) + order.pace * share
            if order.done:
                notices.append(
                    f"{order.country} finished selling ${order.total:,.0f}bn of Treasuries"
                )
        s.orders = [o for o in s.orders if not o.done]
        target = self.impact.temporary_target(pace, self.market_size, EVAL_TENORS)
        s.temp = self.impact.relax(s.temp, target, days)

        effr_star = self.effr_target()
        sigma_x = logit_sigma_for(p.effr_rate_vol, s.corridor.lower, s.corridor.upper, effr_star)
        s.effr = float(
            corridor_ou_step(
                s.effr,
                lower=s.corridor.lower,
                upper=s.corridor.upper,
                target=effr_star,
                kappa=p.effr_kappa,
                sigma_x=sigma_x,
                dt=dt_years,
                rng=self.rng,
            )
        )
        return notices

    def check_invariants(self) -> None:
        """Asserted on every tick; a failure is a bug, not a market event."""
        s = self.state
        if not s.corridor.lower <= s.effr <= s.corridor.upper:
            raise AssertionError(
                f"EFFR {s.effr:.6f} outside [{s.corridor.lower}, {s.corridor.upper}]"
            )
        gap = s.sheet.identity_gap()
        if abs(gap) > 1e-6:
            raise AssertionError(f"Fed balance-sheet identity broken by {gap:.3e}")
        if s.sheet.reserves < self.params.reserves_floor - 1e-9 or s.sheet.on_rrp < -1e-9:
            raise AssertionError("reserves or ON RRP went below their floor")

    # ------------------------------------------------------------------ shocks and policy

    def policy_curve_change(self, change: float) -> dict[str, float]:
        """How the par curve would move for a policy move, without making it."""
        zeros = self._zeros()
        now, moved = par_from_zero(zeros), par_from_zero(zeros + change * self._policy_loading)
        return {k: moved[k] - now[k] for k in now}

    def set_policy(self, change: float) -> None:
        """Move the target range; EFFR moves with it on the effective date."""
        s = self.state
        s.corridor = s.corridor.shifted(change)
        s.effr = min(max(s.effr + change, s.corridor.lower), s.corridor.upper)
        s.policy_shift += change

    def set_qt(self, monthly_total: float | None) -> QTPlan:
        """``None`` stops runoff; otherwise split like the FOMC's 2022 plan."""
        self.state.qt = (
            QTPlan(0.0, 0.0) if monthly_total is None else QTPlan.from_total(monthly_total)
        )
        self.state.qt_halted = False
        return self.state.qt

    def sell(
        self, country: str, amount: float, days: float, mix: str | dict[str, float]
    ) -> SaleOrder:
        held = self.state.holdings.get(country)
        if held is None:
            raise ValueError(f"no TIC holdings recorded for {country}")
        committed = sum(o.total - o.sold for o in self.state.orders if o.country == country)
        if amount <= 0 or amount > held - committed + 1e-9:
            raise ValueError(f"{country} holds ${held - committed:,.1f}bn not already being sold")
        if days <= 0:
            raise ValueError("the pace must be a positive number of days")
        shares = {k: v / amount for k, v in split_sale(amount, mix).items()}
        order = SaleOrder(country, amount, days, shares)
        self.state.orders.append(order)
        return order

    def project_sale(
        self, amount: float, days: float, mix: str | dict[str, float]
    ) -> dict[str, dict[str, float]]:
        """Deterministic par-yield changes from a sale alone: at its end and in the long run.

        The temporary part builds toward its target with the model half-life while selling
        lasts; the long run keeps only the permanent part.
        """
        sold = split_sale(amount, mix)
        pace = {bucket: q / days for bucket, q in sold.items()}
        target = self.impact.temporary_target(pace, self.market_size, EVAL_TENORS)
        temp_end = target * (1 - 2 ** (-days / self.impact.half_life_days))
        permanent = self.impact.permanent(sold, self.market_size, EVAL_TENORS)
        zeros = self._zeros()
        now = par_from_zero(zeros)
        end, long_run = (
            par_from_zero(zeros + permanent + temp_end),
            par_from_zero(zeros + permanent),
        )
        return {
            "end_of_sale": {k: end[k] - now[k] for k in DISPLAY_TENORS},
            "long_run": {k: long_run[k] - now[k] for k in DISPLAY_TENORS},
        }

    # ------------------------------------------------------------------ analytics

    def treasury_10ye_ratio(self, par: dict[str, float] | None = None) -> float:
        """10-year equivalents per dollar of new issuance at the steady-state mix."""
        par = par or self.par_curve()
        mix = self.anchors.issuance_mix
        duration = sum(
            share * par_duration(interp_par(par, tenor), tenor)
            for tenor, share in zip(mix.tenors, mix.shares, strict=True)
        )
        return duration / par_duration(par["10Y"], 10.0)

    def mbs_10ye_ratio(self, par: dict[str, float] | None = None) -> float:
        par = par or self.par_curve()
        return self.params.mbs_duration / par_duration(par["10Y"], 10.0)

    def price_yield(self, tenor: str, shifts_bp: list[float]) -> PriceYieldPanel:
        """PY panel: a par bond at the current yield, its risk, and the approximation overlay."""
        if tenor not in COUPON_TENORS:
            raise ValueError(f"PY takes a coupon tenor: {', '.join(COUPON_TENORS)}")
        y = self.par_curve()[tenor]
        cf = CashFlows.bullet(y, periods=round(TENOR_YEARS[tenor] * 2), freq=2)
        risk = risk_measures(cf, y, 2)
        profile = price_yield_profile(cf, y, 2, np.array(shifts_bp) * 1e-4)
        return PriceYieldPanel(
            tenor=tenor,
            ytm=y,
            price=risk.price,
            macaulay=risk.macaulay_duration,
            modified=risk.modified_duration,
            convexity=risk.convexity,
            dv01=risk.dv01,
            shifts_bp=list(shifts_bp),
            exact=profile.exact.tolist(),
            duration_only=profile.duration_only.tolist(),
            duration_convexity=profile.duration_convexity.tolist(),
        )

    def _debt_path(self, par: dict[str, float], months: int) -> DebtPath:
        a = self.anchors
        return project_debt_service(
            a.ladder,
            start=a.mspd_as_of,
            months=months,
            yield_at=lambda _month, tenor: interp_par(par, tenor),
            mix=a.issuance_mix,
            monthly_deficit=a.deficit_12m / 12,
            nominal_gdp=a.nominal_gdp,
            annual_receipts=a.receipts_12m,
        )

    def debt_service(
        self, months: int = 120, shocked_par: dict[str, float] | None = None
    ) -> DebtComparison:
        """Interest cost with today's curve held flat vs the simulated curve held flat.

        Pass ``shocked_par`` (from ``par_curve()``) to run this off the event loop: it then
        touches only immutable anchors.
        """
        base = self._debt_path(self.anchors.par_curve, months)
        shock = self._debt_path(shocked_par or self.par_curve(), months)
        marks = [m for m in (11, 59, months - 1) if m < months]
        return DebtComparison(
            start=self.anchors.mspd_as_of.isoformat(),
            months=[d.isoformat() for d in base.months],
            baseline_interest=base.interest.tolist(),
            shocked_interest=shock.interest.tolist(),
            baseline_to_gdp=base.interest_to_gdp.tolist(),
            shocked_to_gdp=shock.interest_to_gdp.tolist(),
            baseline_to_receipts=base.interest_to_receipts.tolist(),
            shocked_to_receipts=shock.interest_to_receipts.tolist(),
            delta_by_year={
                str((m + 1) // 12): float(shock.interest[m] - base.interest[m]) for m in marks
            },
        )

    def qt_projection(self, monthly_total: float, months: int = 24) -> QTProjection:
        """Deterministic path of a QT plan: reserves, EFFR − IORB and the 10-year term premium."""
        plan = QTPlan.from_total(monthly_total)
        sheet, tenye = self.state.sheet, self.state.qt_10ye
        par = self.par_curve()
        t_ratio, m_ratio = self.treasury_10ye_ratio(par), self.mbs_10ye_ratio(par)
        start_tp = self.qt_term_premium()
        reserves, spreads, tp_change = [], [], []
        for _ in range(months):
            t_amt, m_amt, _ = self._runoff(sheet, *plan.runoff(AVERAGE_MONTH_DAYS))
            sheet = sheet.run_off(t_amt, m_amt)
            tenye += t_amt * t_ratio + m_amt * m_ratio
            reserves.append(sheet.reserves)
            spreads.append(
                float(self.anchors.reserve_curve.spread(sheet.reserves / self.anchors.bank_assets))
            )
            tp_change.append(term_premium_effect(tenye, self.anchors.nominal_gdp) - start_tp)
        return QTProjection(
            monthly_total=monthly_total,
            reserves=reserves,
            effr_iorb_spread=spreads,
            ten_year_term_premium_change=tp_change,
        )

    # ------------------------------------------------------------------ snapshots

    def snapshot(self) -> dict[str, object]:
        s = self.state
        par = self.par_curve()
        return {
            "curve": {k: par[k] for k in DISPLAY_TENORS},
            "effr": s.effr,
            "effr_target": self.effr_target(),
            "corridor": {
                "lower": s.corridor.lower,
                "upper": s.corridor.upper,
                "iorb": s.corridor.iorb,
                "on_rrp": s.corridor.on_rrp,
                "srf": s.corridor.srf_rate,
            },
            "reserves": s.sheet.reserves,
            "on_rrp_balance": s.sheet.on_rrp,
            "reserves_ratio": self.reserves_ratio(),
            "fed_assets": s.sheet.total_assets,
            "qt": {
                "treasury_cap": s.qt.treasury_cap,
                "mbs_cap": s.qt.mbs_cap,
                "halted": s.qt_halted,
            },
            "term_premium": self.anchors.term_premium + s.tp_dev + self.qt_term_premium(),
            "dollar_index": self.anchors.dollar_index * (1 + s.dollar_shift_pct / 100),
            "selling": [
                {"country": o.country, "total": o.total, "sold": o.sold, "days": o.days}
                for o in s.orders
            ],
            "as_of": self.anchors.as_of.isoformat(),
        }
