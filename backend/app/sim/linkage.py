"""The US → India linkage (Module C): the chain's parameters calibrated on public data, and the
rupee and RBI's reserves it starts from.

Calibration, each an OLS with Newey–West errors (the results are listed in ASSUMPTIONS.md):

* Spillover: weekly (Friday to Friday) changes in FBIL's 10-year par yield on those in the US
  10-year (FRED's DGS10), from February 2023, FBIL's daily coverage.
* FPI flows, monthly from 2014 (NSDL's daily net investment summed, US$ billion):
  - debt on the change in the IN−US 10-year differential and in the VIX. India's monthly 10-year
    yield is the OECD's (via FRED), the US one DGS10's monthly mean, the VIX its monthly mean;
  - equity on the change in the US 10-year and in the VIX.
* RBI's absorption: weekly changes in its foreign currency assets (the Weekly Statistical
  Supplement) on weekly FPI flows, with the broad dollar index's change times the previous
  week's assets for valuation. The coefficient is the share of FPI flows that shows up in the
  reserves.
* The rupee: the weekly percentage change in rupees per dollar (FRED's DEXINUS) on weekly FPI
  flows and the dollar index's change. The chain's elasticity is per dollar RBI does not absorb,
  so it is the flow coefficient divided by (1 − s).

``fed_shock`` runs it end to end on the simulators: the Fed moves in the US simulation, the US
10Y's response starts the chain, and the Indian money market takes it from the next business
day.
"""

import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.data.service import DataService
from app.sim.anchors import AnchorError, required_series
from app.sim.india_market import IndiaMarket
from app.sim.us_market import USMarket
from sovereign_engine.linkage import (
    RESPONSES,
    Z90,
    ChainPath,
    FedShock,
    LinkParams,
    MarketStart,
    OlsFit,
    Response,
    ols_hac,
    run_chain,
)

SPILLOVER_FROM = date(2023, 2, 13)
"""FBIL's first daily (.xlsx) G-sec workbook."""
FLOWS_FROM = date(2014, 1, 1)


@dataclass(frozen=True, slots=True)
class LinkAssumptions:
    """The chain's settings that are not estimated (listed in ASSUMPTIONS.md)."""

    hac_lags_monthly: int = 3
    hac_lags_weekly: int = 4
    flow_days: int = 21
    half_life_days: float = 5.0
    response_lag_days: int = 1
    every_days: int = 5
    hike_bp: float = 25.0
    hike_10y: float = 0.54
    """India's 10Y per unit of repo surprise when the G-sec curve is unavailable; otherwise the
    curve's own β(10Y) from the event study (Phase 7), 0.54 on the seed."""
    max_inr_per_bn: float = 2.0
    """A bound on the rupee's elasticity when RBI absorbs nearly everything."""
    horizon_days: int = 30
    """Business days a shock is followed for (the flows arrive over the first 21)."""


@dataclass(frozen=True, slots=True)
class Estimate:
    key: str
    label: str
    value: float
    low: float
    high: float
    """90% interval."""
    n: int
    r2: float
    sample: str
    method: str
    used: float
    """The value the chain uses: the estimate, unless a bound applied."""


@dataclass(frozen=True, slots=True)
class LinkModel:
    params: LinkParams
    estimates: tuple[Estimate, ...]
    inr: float
    """Rupees per dollar: FBIL's reference rate."""
    inr_as_of: date
    reserves_bn: float
    reserves_as_of: date
    assumptions: LinkAssumptions = field(default_factory=LinkAssumptions)

    def estimate(self, key: str) -> Estimate:
        return next(e for e in self.estimates if e.key == key)


def _estimate(
    key: str,
    label: str,
    fit: OlsFit,
    name: str,
    sample: str,
    method: str,
    *,
    used: float | None = None,
) -> Estimate:
    value = fit.value(name)
    low, high = fit.interval(name)
    return Estimate(
        key, label, value, low, high, fit.n, fit.r2, sample, method, value if used is None else used
    )


def _span(index: pd.Index) -> str:
    days = pd.DatetimeIndex(index)
    return f"{days.min():%b %Y}–{days.max():%b %Y}"


def _friday(series: pd.Series) -> pd.Series:
    """The last value of each week ending Friday."""
    return series.sort_index().resample("W-FRI").last()


def fit_spillover(in10y: pd.Series, us10y: pd.Series, lags: int) -> Estimate:
    """Weekly ΔIN10Y on ΔUS10Y (both %, so the slope is per point)."""
    weekly = pd.DataFrame({"in": _friday(in10y), "us": _friday(us10y)}).dropna().diff().dropna()
    fit = ols_hac(weekly["in"].to_numpy(), {"us": weekly["us"].to_numpy()}, lags=lags)
    return _estimate(
        "spillover",
        "India 10Y per US 10Y move",
        fit,
        "us",
        f"weekly, {_span(weekly.index)}",
        "ΔIN10Y on ΔUS10Y (FBIL par 10Y, FRED DGS10)",
    )


def monthly_flows(daily_usd_mn: pd.Series) -> pd.Series:
    """NSDL's daily net investment (US$ million) summed by calendar month, US$ billion."""
    return daily_usd_mn.sort_index().resample("MS").sum(min_count=1) / 1000


def fit_flows(
    debt: pd.Series,
    equity: pd.Series,
    in10y_monthly: pd.Series,
    us10y: pd.Series,
    vix: pd.Series,
    lags: int,
) -> tuple[Estimate, Estimate, Estimate]:
    """Monthly FPI flows (US$ bn): debt on Δ(IN−US 10Y) and ΔVIX; equity on ΔUS10Y and ΔVIX."""
    us = us10y.sort_index().resample("MS").mean()
    frame = pd.DataFrame(
        {
            "debt": monthly_flows(debt),
            "equity": monthly_flows(equity),
            "diff": in10y_monthly.sort_index().resample("MS").last() - us,
            "us": us,
            "vix": vix.sort_index().resample("MS").mean(),
        }
    )
    frame = frame[frame.index >= pd.Timestamp(FLOWS_FROM)]
    change = frame[["diff", "us", "vix"]].diff()
    data = pd.concat([frame[["debt", "equity"]], change], axis=1).dropna()
    debt_fit = ols_hac(
        data["debt"].to_numpy(),
        {"diff": data["diff"].to_numpy(), "vix": data["vix"].to_numpy()},
        lags=lags,
    )
    equity_fit = ols_hac(
        data["equity"].to_numpy(),
        {"us": data["us"].to_numpy(), "vix": data["vix"].to_numpy()},
        lags=lags,
    )
    sample = f"monthly, {_span(data.index)}"
    risk = debt_fit.value("vix") + equity_fit.value("vix")
    risk_se = math.hypot(
        float(debt_fit.se[debt_fit.names.index("vix")]),
        float(equity_fit.se[equity_fit.names.index("vix")]),
    )
    z = Z90
    risk_estimate = Estimate(
        "risk_flow",
        "FPI flows per VIX point (US$ bn a month)",
        risk,
        risk - z * risk_se,
        risk + z * risk_se,
        debt_fit.n,
        float("nan"),
        sample,
        "the debt and equity regressions' VIX slopes, summed (errors treated as independent)",
        risk,
    )
    return (
        _estimate(
            "debt_flow",
            "FPI debt flows per point of IN−US 10Y (US$ bn a month)",
            debt_fit,
            "diff",
            sample,
            "debt flows on Δ(IN10Y − US10Y) and ΔVIX (NSDL; OECD India 10Y, DGS10, VIX)",
        ),
        _estimate(
            "equity_flow",
            "FPI equity flows per point of US 10Y (US$ bn a month)",
            equity_fit,
            "us",
            sample,
            "equity flows on ΔUS10Y and ΔVIX (NSDL; DGS10, VIX)",
        ),
        risk_estimate,
    )


def _weekly(
    fca_mn: pd.Series, fpi_total_mn: pd.Series, dxy: pd.Series, inr: pd.Series
) -> pd.DataFrame:
    fca = _friday(fca_mn) / 1000
    frame = pd.DataFrame(
        {
            "fca": fca,
            "fca_change": fca.diff(),
            "fpi": fpi_total_mn.sort_index().resample("W-FRI").sum(min_count=1) / 1000,
            "dxy": _friday(dxy).pct_change(fill_method=None) * 100,
            "inr": _friday(inr).pct_change(fill_method=None) * 100,
        }
    )
    frame["valuation"] = frame["dxy"] / 100 * frame["fca"].shift(1)
    return frame[frame.index >= pd.Timestamp(FLOWS_FROM)].dropna()


def fit_absorption(
    fca_mn: pd.Series, fpi_total_mn: pd.Series, dxy: pd.Series, inr: pd.Series, lags: int
) -> Estimate:
    """Weekly ΔFCA (US$ bn) on weekly FPI flows (US$ bn), valuation controlled."""
    w = _weekly(fca_mn, fpi_total_mn, dxy, inr)
    fit = ols_hac(
        w["fca_change"].to_numpy(),
        {"fpi": w["fpi"].to_numpy(), "valuation": w["valuation"].to_numpy()},
        lags=lags,
    )
    value = fit.value("fpi")
    return _estimate(
        "intervention",
        "Share of FPI flows RBI absorbs in its reserves",
        fit,
        "fpi",
        f"weekly, {_span(w.index)}",
        "ΔFCA on FPI flows and the dollar index's valuation effect (WSS, NSDL, FRED DTWEXBGS)",
        used=min(max(value, 0.0), 1.0),
    )


def fit_rupee(
    inr: pd.Series,
    fpi_total_mn: pd.Series,
    dxy: pd.Series,
    fca_mn: pd.Series,
    absorbed: float,
    lags: int,
    cap: float,
) -> Estimate:
    """Weekly %ΔINR on weekly FPI flows (US$ bn) and %ΔDXY; per unabsorbed dollar: ÷ (1 − s)."""
    w = _weekly(fca_mn, fpi_total_mn, dxy, inr)
    fit = ols_hac(
        w["inr"].to_numpy(), {"fpi": w["fpi"].to_numpy(), "dxy": w["dxy"].to_numpy()}, lags=lags
    )
    raw = -fit.value("fpi")
    low, high = sorted(-v for v in fit.interval("fpi"))
    unabsorbed = max(1.0 - absorbed, 1e-9)
    used = min(max(raw / unabsorbed, 0.0), cap)
    return Estimate(
        "inr_per_bn",
        "Rupee depreciation per US$ bn of unabsorbed outflow (%)",
        raw / unabsorbed,
        low / unabsorbed,
        high / unabsorbed,
        fit.n,
        fit.r2,
        f"weekly, {_span(w.index)}",
        "%ΔINR on FPI flows and %ΔDXY (FRED DEXINUS, NSDL, DTWEXBGS), divided by 1 − s",
        used,
    )


def _latest(series: pd.Series) -> tuple[date, float]:
    clean = series.dropna().sort_index()
    if clean.empty:
        raise AnchorError(f"no data in {series.name}")
    return pd.Timestamp(clean.index[-1]).date(), float(clean.iloc[-1])


def build_link(service: DataService, assumptions: LinkAssumptions | None = None) -> LinkModel:
    """The chain calibrated on the stored data, with today's rupee and reserves."""
    a = assumptions or LinkAssumptions()

    def series(series_id: str) -> pd.Series:
        return required_series(service, series_id).dropna()

    us10y = series("fred/DGS10")
    spill = fit_spillover(
        series("fbil/gsec/par/10Y").loc[pd.Timestamp(SPILLOVER_FROM) :], us10y, a.hac_lags_weekly
    )
    debt, equity, risk = fit_flows(
        series("nsdl/fpi/debt_usd"),
        series("nsdl/fpi/equity_usd"),
        series("fred/INDIRLTLT01STM"),
        us10y,
        series("fred/VIXCLS"),
        a.hac_lags_monthly,
    )
    fca, total, dxy, inr = (
        series("rbi/wss/fca"),
        series("nsdl/fpi/total_usd"),
        series("fred/DTWEXBGS"),
        series("fred/DEXINUS"),
    )
    absorbed = fit_absorption(fca, total, dxy, inr, a.hac_lags_weekly)
    rupee = fit_rupee(inr, total, dxy, fca, absorbed.used, a.hac_lags_weekly, a.max_inr_per_bn)
    params = LinkParams(
        spillover=spill.used,
        debt_flow=debt.used,
        equity_flow=equity.used,
        risk_flow=risk.used,
        intervention=absorbed.used,
        inr_per_bn=rupee.used,
        flow_days=a.flow_days,
        half_life_days=a.half_life_days,
        response_lag_days=a.response_lag_days,
        omo_every_days=a.every_days,
        hike_bp=a.hike_bp,
        hike_10y=a.hike_10y,
    )
    inr_as_of, inr_now = _latest(series("fbil/usdinr"))
    reserves_as_of, reserves = _latest(series("rbi/wss/reserves"))
    if not np.isfinite([inr_now, reserves]).all():
        raise AnchorError("the rupee or the reserves are not finite")
    return LinkModel(
        params=params,
        estimates=(spill, debt, equity, risk, absorbed, rupee),
        inr=inr_now,
        inr_as_of=inr_as_of,
        reserves_bn=reserves / 1000,
        reserves_as_of=reserves_as_of,
        assumptions=a,
    )


# ----------------------------------------------------------------------- runs

RESPONSE_LABELS: dict[str, str] = {
    "none": "none: RBI lets rates move",
    "vrr": "weekly VRR (VRRR) auctions of the drain so far",
    "omo": "weekly OMO purchases (sales) of the drain not yet offset",
    "swap": "a buy/sell swap of the dollars it expects to sell",
    "hike": "a repo hike",
}


@dataclass(frozen=True, slots=True)
class LinkRun:
    """One US shock run through the chain on the simulators."""

    path: ChainPath
    days: tuple[date, ...]
    """The business day each chain day lands on in the Indian market."""
    us_curve_bp: dict[str, float]
    """How the US par curve moved (bp)."""
    started: datetime


def _start(india: IndiaMarket, model: LinkModel) -> MarketStart:
    return MarketStart(
        inr=india.inr if india.inr is not None else model.inr,
        reserves_bn=india.reserves_bn if india.reserves_bn is not None else model.reserves_bn,
        surplus_cr=india.projected_surplus(),
        ndtl_cr=india.ndtl(),
        repo=india.repo,
    )


def _chain(
    india: IndiaMarket,
    model: LinkModel,
    fed_bp: float,
    us10y_bp: float,
    vix: float,
    response: Response,
) -> ChainPath:
    a = india.anchors
    # A repo hike moves India's curve as the simulated G-sec curve does: by its own β.
    params = replace(
        model.params,
        hike_10y=india.gsec.betas["10Y"] if india.gsec is not None else model.params.hike_10y,
        hike_3m=india.tbill_beta["3M"],
    )
    return run_chain(
        FedShock(fed_bp, us10y_bp, vix),
        _start(india, model),
        params,
        response=response,
        horizon_days=model.assumptions.horizon_days,
        liquidity_map=a.liquidity_map,
        tbill_slope_bp=a.tbill_slopes["3M"] * 1e4,
    )


def preview(
    us: USMarket, india: IndiaMarket, model: LinkModel, change: float, response: Response = "none"
) -> ChainPath:
    """What a Fed move would do, without making it."""
    us10y = us.policy_curve_change(change)["10Y"]
    return _chain(india, model, change * 1e4, us10y * 1e4, 0.0, response)


def fed_shock(
    us: USMarket,
    india: IndiaMarket,
    model: LinkModel,
    change: float,
    *,
    response: Response = "none",
    vix: float = 0.0,
    now: datetime,
) -> LinkRun:
    """Move the Fed in the US simulation and run the chain into the Indian market."""
    if response not in RESPONSES:
        raise ValueError(f"response must be one of {RESPONSES}")
    before = us.par_curve()
    us.set_policy(change)
    after = us.par_curve()
    moved = {k: (after[k] - before[k]) * 1e4 for k in after}
    path = _chain(india, model, change * 1e4, moved["10Y"], vix, response)
    problems = path.check()
    if problems:
        raise AssertionError(f"the linkage chain does not balance: {problems}")
    days = india.schedule_link(path)
    return LinkRun(path, tuple(days), moved, now)


def _clean(value: float) -> float | None:
    return value if math.isfinite(value) else None


def link_panel(
    model: LinkModel,
    india: IndiaMarket,
    run: LinkRun | None,
    shown: ChainPath,
    *,
    today: date,
) -> dict[str, Any]:
    """The LINK panel: the chain's nodes for a run (or a preview), its daily path, how far the
    simulation has got, and the calibration behind each link."""
    t = shown.totals()
    start = shown.start
    p = shown.params
    nodes = [
        {"key": "fed", "label": "Fed funds", "value": t["fed_bp"], "unit": "bp", "detail": ""},
        {
            "key": "us10y",
            "label": "US 10Y",
            "value": t["us10y_bp"],
            "unit": "bp",
            "detail": "the US simulation's response",
        },
        {
            "key": "differential",
            "label": "IN − US 10Y",
            "value": t["differential_bp"],
            "unit": "bp",
            "detail": f"India 10Y {t['in10y_bp']:+.1f} bp (spillover {p.spillover:.2f})",
        },
        {
            "key": "fpi",
            "label": "FPI flows",
            "value": t["fpi_bn"],
            "unit": "US$ bn",
            "detail": f"over {p.flow_days} business days",
        },
        {
            "key": "rbi",
            "label": "RBI's dollar trades",
            "value": t["rbi_bn"],
            "unit": "US$ bn",
            "detail": f"{p.intervention:.0%} of the flow; reserves "
            f"${start.reserves_bn + t['reserves_bn']:,.1f}bn",
        },
        {
            "key": "inr",
            "label": "Rupee",
            "value": t["inr_pct"],
            "unit": "%",
            "detail": f"₹{t['inr']:.2f} per $ (+ is weaker)",
        },
        {
            "key": "liquidity",
            "label": "Rupee liquidity",
            "value": t["drain_cr"] + t["injection_cr"],
            "unit": "₹ cr",
            "detail": f"{t['surplus_pct']:+.3f}% of NDTL",
        },
        {
            "key": "wacr",
            "label": "WACR",
            "value": t["wacr_bp"],
            "unit": "bp",
            "detail": f"3M T-bill {t['tbill_bp']:+.1f} bp",
        },
        {
            "key": "response",
            "label": "RBI's response",
            "value": t["vrr_cr"] if shown.response == "vrr" else t["injection_cr"],
            "unit": "₹ cr" if shown.response != "hike" else "bp",
            "detail": RESPONSE_LABELS[shown.response],
        },
    ]
    if shown.response == "hike":
        nodes[-1]["value"] = t["repo_bp"]
    elapsed = 0 if run is None else sum(1 for d in run.days if d <= today)
    days = [d.isoformat() for d in run.days] if run is not None else None
    return {
        "mode": "preview" if run is None else "run",
        "response": shown.response,
        "responses": list(RESPONSES),
        "response_labels": RESPONSE_LABELS,
        "nodes": nodes,
        "progress": {"day": elapsed, "days": shown.days, "dates": days},
        "path": {
            "fpi_bn": np.cumsum(shown.fpi_bn).tolist(),
            "rbi_bn": np.cumsum(shown.rbi_bn).tolist(),
            "inr": shown.inr.tolist(),
            "reserves_bn": shown.reserves_bn.tolist(),
            "surplus_pct": (shown.surplus_cr / start.ndtl_cr * 100).tolist(),
            "wacr_bp": shown.wacr_bp.tolist(),
            "vrr_cr": shown.vrr_cr.tolist(),
        },
        "live": {
            "inr": india.inr if india.inr is not None else model.inr,
            "reserves_bn": india.reserves_bn
            if india.reserves_bn is not None
            else model.reserves_bn,
            "surplus_pct": india.surplus_pct(),
            "wacr": india.wacr(),
            "repo": india.repo,
            "runs": len(india.fx_runs),
        },
        "anchors": {
            "inr": model.inr,
            "inr_as_of": model.inr_as_of.isoformat(),
            "reserves_bn": model.reserves_bn,
            "reserves_as_of": model.reserves_as_of.isoformat(),
        },
        "estimates": [
            {
                "key": e.key,
                "label": e.label,
                "value": _clean(e.value),
                "low": _clean(e.low),
                "high": _clean(e.high),
                "used": e.used,
                "n": e.n,
                "r2": _clean(e.r2),
                "sample": e.sample,
                "method": e.method,
            }
            for e in model.estimates
        ],
        "assumptions": {
            "flow_days": p.flow_days,
            "half_life_days": p.half_life_days,
            "response_lag_days": p.response_lag_days,
            "every_days": p.omo_every_days,
            "hike_bp": p.hike_bp,
            "hike_10y": p.hike_10y,
            "horizon_days": shown.days,
        },
    }
