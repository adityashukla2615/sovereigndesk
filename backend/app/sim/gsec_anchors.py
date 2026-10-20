"""Starting values and fitted behaviour for India's G-sec curve, from FBIL and RBI data.

* The curve: the 91/182/364-day T-bills at FBIL's benchmark yields (the money market's, so the
  same numbers as the WACR panel), then FBIL's par yields for the coupon tenors on its latest
  publication (often a week old, so labelled STALE), fitted with Nelson–Siegel–Svensson: bills
  at their simple yield, bonds at par. FBIL's par curve also has 3, 6 and 12-month points, values
  of its own fitted curve that can differ from the bills' benchmarks by several basis points; the
  event study uses them (one curve from one source), the live curve uses the bills.
* The repo pass-through: the event study on every repo change since 8 Apr 2022 (repo is the
  midpoint of the SDF and MSF in RBI's Money Market Operations releases), each change measured
  from FBIL's previous publication to the day's close.
* Day-to-day moves: FBIL's daily par-yield changes on the coupon tenors, split each day onto
  the pass-through's two loadings (expectations and term premium) by least squares.
* The spread: FBIL's 10-year par yield against Treasury's, day by day.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.data.catalog import FBIL_GSEC_TENORS
from app.data.service import DataService
from app.sim.anchors import AnchorError, required_series
from sovereign_engine.curves.nss import NssFit, Quote, fit_nss_quotes
from sovereign_engine.india.passthrough import (
    EventStudy,
    PassThroughFit,
    event_study,
    fit_passthrough,
    policy_changes,
)
from sovereign_engine.rates.loadings import expectations_loading, term_premium_loading

GSEC = "fbil/gsec/par/"
BILL_DAYS: dict[str, int] = {"3M": 91, "6M": 182, "1Y": 364}
"""The curve's bill points (91/182/364-day T-bills) and their days to maturity."""
TBILL_OF: dict[str, str] = {"3M": "3M", "6M": "6M", "1Y": "12M"}
"""G-sec curve label → the money market's T-bill benchmark label."""
COUPON_TENORS: tuple[str, ...] = tuple(t for t in FBIL_GSEC_TENORS if t not in BILL_DAYS)
TERM_PREMIUM_SCALE = 7.0
"""Maturity scale of the term-premium loading (years); the US curve uses the same."""
MAX_GAP_DAYS = 7
"""Longest gap between publications that still counts as daily coverage."""


@dataclass(frozen=True, slots=True)
class RepoEvent:
    day: date
    before: date
    """FBIL's previous publication, the start of the window."""
    change: float
    """Repo change (decimal)."""
    moves: dict[str, float]
    """Par-yield change by tenor over the window (decimal)."""


@dataclass(frozen=True, slots=True)
class FactorModel:
    """Daily changes of the two curve factors, from FBIL's history away from repo changes."""

    level_sd: float
    """S.d. of the daily expectations-factor change (decimal, loading one at the front end)."""
    tp_sd: float
    """S.d. of the daily term-premium change (decimal, loading one at 10 years)."""
    correlation: float
    days: int
    residual_bp: float
    """RMS of what the two loadings leave unexplained in a day's move, basis points."""


@dataclass(frozen=True, slots=True)
class GsecAnchors:
    as_of: date
    """FBIL's latest publication."""
    par: dict[str, float]
    """FBIL's par curve by tenor (decimals; the 3-month point is a simple yield)."""
    close: dict[str, float]
    """The curve's market points on ``as_of``: T-bill benchmarks, then FBIL's coupon par yields."""
    repo: float
    """Repo on ``as_of``: the curve's pass-through shifts are measured from it."""
    fit: NssFit
    """NSS fitted to ``close``."""
    events: tuple[RepoEvent, ...]
    study: EventStudy
    passthrough: PassThroughFit
    factors: FactorModel
    daily_from: date
    """First day of continuous (daily) coverage; before it only event windows were fetched."""
    spread_history: tuple[tuple[date, float, float], ...] = ()
    """(day, India 10Y, US 10Y) par yields (decimals) since ``daily_from``."""
    quality: dict[str, str] = field(default_factory=dict)


def _par_frame(service: DataService) -> pd.DataFrame:
    columns = {t: required_series(service, GSEC + t) / 100 for t in FBIL_GSEC_TENORS}
    frame = pd.DataFrame(columns).sort_index()
    return frame[~frame.index.duplicated(keep="last")].dropna()


def daily_coverage_start(days: pd.DatetimeIndex, max_gap_days: int = MAX_GAP_DAYS) -> date:
    """The first day after which no two publications are more than ``max_gap_days`` apart."""
    gaps = np.flatnonzero(np.diff(days.values).astype("timedelta64[D]").astype(int) > max_gap_days)
    return (days[gaps[-1] + 1] if gaps.size else days[0]).date()


def repo_events(par: pd.DataFrame, repo: pd.Series) -> list[RepoEvent]:
    """Each repo change with FBIL publications on the day and before it."""
    repo = repo.dropna().sort_index()
    published = par.index
    events = []
    days = [d.date() for d in pd.DatetimeIndex(repo.index)]
    for day, change in policy_changes(days, repo.to_numpy()):
        stamp = pd.Timestamp(day)
        earlier = published[published < stamp]
        if stamp not in published or earlier.empty:
            continue
        before = earlier[-1]
        moves = {str(k): float(v) for k, v in (par.loc[stamp] - par.loc[before]).items()}
        events.append(RepoEvent(day, before.date(), change, moves))
    return events


def fit_factors(par: pd.DataFrame, events: list[RepoEvent], fit: PassThroughFit) -> FactorModel:
    """Split each day's coupon-tenor moves onto the expectations and term-premium loadings."""
    years = np.array([FBIL_GSEC_TENORS[t] for t in COUPON_TENORS])
    design = np.column_stack(
        (
            expectations_loading(years, fit.curve.kappa),
            term_premium_loading(years, fit.curve.scale),
        )
    )
    moves = par[list(COUPON_TENORS)]
    gaps = moves.index.to_series().diff().dt.days
    changes = moves.diff()[(gaps > 0) & (gaps <= MAX_GAP_DAYS)]
    changes = changes[~changes.index.isin([pd.Timestamp(e.day) for e in events])].dropna()
    if len(changes) < 30:
        raise AnchorError("fewer than 30 daily G-sec changes to calibrate the curve's noise")
    factors, *_ = np.linalg.lstsq(design, changes.to_numpy().T, rcond=None)
    fitted = design @ factors
    resid = changes.to_numpy().T - fitted
    level, tp = factors
    return FactorModel(
        level_sd=float(np.std(level, ddof=1)),
        tp_sd=float(np.std(tp, ddof=1)),
        correlation=float(np.corrcoef(level, tp)[0, 1]),
        days=len(changes),
        residual_bp=float(np.sqrt(np.mean(resid**2)) * 1e4),
    )


def quotes_of(points: dict[str, float]) -> list[Quote]:
    """The curve's market points as NSS quotes: bills at simple yields, the rest at par."""
    return [
        Quote(BILL_DAYS[t] / 365, points[t], "bill")
        if t in BILL_DAYS
        else Quote(FBIL_GSEC_TENORS[t], points[t], "par")
        for t in FBIL_GSEC_TENORS
    ]


def _spread_history(
    service: DataService, par: pd.DataFrame, start: date
) -> tuple[tuple[date, float, float], ...]:
    try:
        us = required_series(service, "ust/par/10Y", start=start) / 100
    except AnchorError:
        return ()
    india = par.loc[par.index >= pd.Timestamp(start), "10Y"]
    joined = pd.DataFrame({"india": india, "us": us}).dropna()
    return tuple(
        (d.date(), float(i), float(u))
        for d, i, u in zip(
            pd.DatetimeIndex(joined.index), joined["india"], joined["us"], strict=True
        )
    )


def build_gsec_anchors(
    service: DataService, repo: pd.Series, tbills: dict[str, float]
) -> GsecAnchors:
    """``repo``: the daily repo rate (decimal), e.g. the SDF/MSF midpoint from RBI's releases;
    ``tbills``: FBIL's latest T-bill benchmarks by the money market's labels (3M, 6M, 12M)."""
    par = _par_frame(service)
    if par.empty:
        raise AnchorError("FBIL's G-sec par yields have no complete day")
    events = repo_events(par, repo)
    if len(events) < 3:
        raise AnchorError(f"only {len(events)} repo changes have FBIL yields around them")
    tenors = np.array(list(FBIL_GSEC_TENORS.values()))
    labels = list(FBIL_GSEC_TENORS)
    study = event_study(
        tenors,
        np.array([e.change for e in events]),
        np.array([[e.moves[t] for t in labels] for e in events]),
    )
    passthrough = fit_passthrough(study, scale=TERM_PREMIUM_SCALE)
    daily_from = daily_coverage_start(pd.DatetimeIndex(par.index))
    latest = par.index[-1]
    points = {t: float(par.loc[latest, t]) for t in labels}
    close = {t: tbills[TBILL_OF[t]] if t in BILL_DAYS else points[t] for t in labels}
    on_day = repo[repo.index <= latest].dropna()
    if on_day.empty:
        raise AnchorError("no repo rate on or before FBIL's latest publication")
    infos = {i.series_id: i.label for i in service.series_info()}
    return GsecAnchors(
        as_of=latest.date(),
        par=points,
        close=close,
        repo=float(on_day.iloc[-1]),
        fit=fit_nss_quotes(quotes_of(close)),
        events=tuple(events),
        study=study,
        passthrough=passthrough,
        factors=fit_factors(par[par.index >= pd.Timestamp(daily_from)], events, passthrough),
        daily_from=daily_from,
        spread_history=_spread_history(service, par, daily_from),
        quality={sid: label for sid, label in infos.items() if sid.startswith(GSEC)},
    )
