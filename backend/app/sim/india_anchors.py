"""Starting values and fitted behaviour for the India simulation, from the latest real data.

Every number comes from a stored series or is fitted to stored history (RBI's daily Money
Market Operations since 8 Apr 2022, FBIL's T-bill benchmarks); a missing input fails the build.
The G-sec curve (FBIL's par yields, ``gsec_anchors``) is optional: without it the money market
still runs and the reason is recorded. The bank universe the simulator builds on these anchors
is SYNTHETIC.
"""

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.data.service import DataService
from app.sim.anchors import AnchorError, required_latest, required_series
from app.sim.gsec_anchors import GsecAnchors, build_gsec_anchors
from sovereign_engine.india.banks import implied_ndtl
from sovereign_engine.india.excursions import (
    DeviationModel,
    calibrate_deviations,
    excursion_shares,
)
from sovereign_engine.india.liquidity_map import (
    LiquidityMap,
    LiquidityMapFit,
    fit_liquidity_map,
)
from sovereign_engine.india.reaction import ReactionCurve, fit_reaction
from sovereign_engine.india.rules import crr_on, in_icrr_period

MMO = "rbi/mmo/"
TBILL_TENORS: tuple[str, ...] = ("3M", "6M", "12M")
ADVANCE_TAX_MONTHS = (3, 6, 9, 12)
ADVANCE_TAX_DAY = 15
GST_DAY = 20
EVENT_HALF_WINDOW = 2
"""Days either side of a tax date over which its drain is measured (and spread in simulation)."""


@dataclass(frozen=True, slots=True)
class TaxCycle:
    advance_tax_drain: float
    """Median fall in surplus across 13-17 Mar/Jun/Sep/Dec, ₹ crore."""
    gst_drain: float
    """Median fall in surplus across the 18th-22nd of other months, ₹ crore."""
    returned_by_day: dict[int, float]
    """Measured median share of an advance-tax drain back in the system N days later."""
    events: int


@dataclass(frozen=True, slots=True)
class SegmentSpreads:
    """Medians over the last year, decimals relative to WACR; volumes as multiples of call."""

    treps: float
    market_repo: float
    notice: float
    term: float
    treps_volume: float
    market_repo_volume: float
    notice_volume: float
    term_volume: float


@dataclass(frozen=True, slots=True)
class Reaction:
    vrr: ReactionCurve
    vrrr: ReactionCurve
    vrr_size: float
    """Median new VRR operation, ₹ crore."""
    vrrr_size: float
    vrr_days: int
    vrrr_days: int


@dataclass(frozen=True, slots=True)
class Excursions:
    """How often real WACR left RBI's corridor, and how well the deviation model matches it."""

    trading_days: int
    below_sdf: int
    above_msf: int
    weekdays: int
    """Weekdays in the map fit (the simulator trades Monday to Friday)."""
    weekday_below: int
    weekday_above: int
    simulated_below: float
    """Share of days below the SDF when the calibrated model runs over the historical path."""
    simulated_above: float
    floor_gap: float
    """Lowest WACR − SDF printed (decimal, ≤ 0): realistic mode's floor."""
    ceiling_gap: float
    """Highest WACR − MSF printed (≥ 0): realistic mode's ceiling."""


@dataclass(frozen=True, slots=True)
class INAnchors:
    as_of: date
    """Latest Money Market Operations release."""
    repo: float
    sdf: float
    msf: float
    crr: float
    slr: float
    ndtl: float
    """₹ crore, implied by the fortnight's CRR requirement."""
    crr_requirement: float
    surplus: float
    """System surplus (net LAF absorption, −F), ₹ crore."""
    vrr_outstanding: float
    vrrr_outstanding: float
    durable_liquidity: float
    durable_as_of: date
    wacr: float
    wacr_as_of: date
    call_volume: float
    """Median weekday call volume over the last year, ₹ crore."""
    liquidity_map: LiquidityMap
    map_rmse_bp: float
    map_points: int
    map_residual_ar1: float
    map_residual: float
    """Latest day's WACR − repo minus the map's prediction (decimal)."""
    spreads: SegmentSpreads
    tbills: dict[str, float]
    tbill_as_of: date
    tbill_slopes: dict[str, float]
    """Change in T-bill − repo per point of surplus (decimal), never positive."""
    tbill_slopes_fitted: dict[str, float]
    tax: TaxCycle
    noise_sd: float
    """Robust s.d. of the daily change in surplus away from tax dates, ₹ crore."""
    ndtl_growth: float
    """NDTL growth over the last year (log, per year)."""
    reaction: Reaction
    deviations: DeviationModel
    """WACR's daily deviation from the map, tails calibrated to the corridor excursions."""
    excursions: Excursions
    history: list[tuple[date, float]] = field(default_factory=list)
    """Real WACR − repo (decimal) by day over the last year, for the heatmap overlay."""
    quality: dict[str, str] = field(default_factory=dict)
    gsec: GsecAnchors | None = None
    """The G-sec curve's anchors, or None when FBIL's par yields could not be used."""
    gsec_error: str | None = None

    @property
    def surplus_pct(self) -> float:
        return self.surplus / self.ndtl * 100


def _frame(service: DataService) -> pd.DataFrame:
    names = {
        "wacr": "wacr",
        "sdf_rate": "sdf_rate",
        "msf_rate": "msf_rate",
        "net_liquidity": "F",
        "crr_requirement": "req",
        "call_volume": "call_volume",
        "treps_rate": "treps",
        "treps_volume": "treps_volume",
        "market_repo_rate": "market_repo",
        "market_repo_volume": "market_repo_volume",
        "notice_rate": "notice",
        "notice_volume": "notice_volume",
        "term_low": "term_low",
        "term_high": "term_high",
        "term_volume": "term_volume",
        "vrr_amount": "vrr",
        "vrrr_amount": "vrrr",
    }
    optional = {"vrr_amount", "vrrr_amount", "notice_rate", "notice_volume", "term_volume"}
    columns: dict[str, pd.Series] = {}
    for remote, name in names.items():
        try:
            columns[name] = required_series(service, MMO + remote)
        except AnchorError:
            if remote not in optional:
                raise
            columns[name] = pd.Series(dtype=float)
    frame = pd.DataFrame(columns).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame[["vrr", "vrrr"]] = frame[["vrr", "vrrr"]].fillna(0.0)
    for col in ("wacr", "sdf_rate", "msf_rate", "treps", "market_repo", "notice"):
        frame[col] = frame[col] / 100
    frame["term"] = (frame["term_low"] + frame["term_high"]) / 200
    frame["repo"] = (frame["sdf_rate"] + frame["msf_rate"]) / 2  # SDF and MSF are repo ∓ 25 bp
    frame["crr"] = [crr_on(d.date()) for d in frame.index]
    frame["ndtl"] = frame["req"] / frame["crr"]
    frame["S"] = -frame["F"]
    frame["ell"] = frame["S"] / frame["ndtl"] * 100
    return frame


def _weekdays(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[pd.DatetimeIndex(frame.index).day_of_week < 5]


def _fit_map(frame: pd.DataFrame) -> tuple[pd.DataFrame, LiquidityMapFit]:
    icrr = np.array([in_icrr_period(d.date()) for d in pd.DatetimeIndex(frame.index)])
    days = _weekdays(frame[~icrr]).dropna(subset=["wacr", "ell", "repo"])
    fit = fit_liquidity_map(days["ell"].to_numpy(), (days["wacr"] - days["repo"]).to_numpy())
    return days, fit


def _excursions(
    frame: pd.DataFrame, days: pd.DataFrame, curve: LiquidityMap
) -> tuple[DeviationModel, Excursions]:
    """Observed corridor excursions, and the deviation model calibrated to the weekday ones."""
    prints = frame.dropna(subset=["wacr", "sdf_rate", "msf_rate"])
    centre = (days["repo"] + curve.spread(days["ell"].to_numpy())).to_numpy()
    resid = days["wacr"].to_numpy() - centre
    lower, upper = days["sdf_rate"].to_numpy(), days["msf_rate"].to_numpy()
    below = days["wacr"].to_numpy() < lower
    above = days["wacr"].to_numpy() > upper
    model = calibrate_deviations(
        resid, centre, lower, upper, float(below.mean()), float(above.mean())
    )
    simulated = excursion_shares(model, centre, lower, upper, np.random.default_rng(11))
    stats = Excursions(
        trading_days=len(prints),
        below_sdf=int((prints["wacr"] < prints["sdf_rate"]).sum()),
        above_msf=int((prints["wacr"] > prints["msf_rate"]).sum()),
        weekdays=len(days),
        weekday_below=int(below.sum()),
        weekday_above=int(above.sum()),
        simulated_below=simulated[0],
        simulated_above=simulated[1],
        floor_gap=min(0.0, float((prints["wacr"] - prints["sdf_rate"]).min())),
        ceiling_gap=max(0.0, float((prints["wacr"] - prints["msf_rate"]).max())),
    )
    return model, stats


def _segment_spreads(frame: pd.DataFrame) -> SegmentSpreads:
    recent = frame[frame.index >= frame.index.max() - pd.Timedelta(days=365)]
    recent = _weekdays(recent).dropna(subset=["wacr", "call_volume"])
    recent = recent[recent["call_volume"] > 0]

    def spread(col: str) -> float:
        value = (recent[col] - recent["wacr"]).median()
        return float(value) if math.isfinite(value) else 0.0

    def ratio(col: str) -> float:
        value = (recent[col] / recent["call_volume"]).median()
        return float(value) if math.isfinite(value) else 0.0

    return SegmentSpreads(
        treps=spread("treps"),
        market_repo=spread("market_repo"),
        notice=spread("notice"),
        term=spread("term"),
        treps_volume=ratio("treps_volume"),
        market_repo_volume=ratio("market_repo_volume"),
        notice_volume=ratio("notice_volume"),
        term_volume=ratio("term_volume"),
    )


def _tax_cycle(frame: pd.DataFrame) -> tuple[TaxCycle, float]:
    surplus = frame["S"].dropna()
    daily = surplus.asfreq("D").ffill()
    first, last = daily.index[0], daily.index[-1]

    def change(day: pd.Timestamp, before: int, after: int) -> float | None:
        a, b = day - pd.Timedelta(days=before), day + pd.Timedelta(days=after)
        if a < first or b > last:
            return None
        return float(daily[b] - daily[a])

    advance: list[float] = []
    gst: list[float] = []
    returned: dict[int, list[float]] = {10: [], 20: []}
    tax_days: set[pd.Timestamp] = set()
    w = EVENT_HALF_WINDOW
    for year in range(first.year, last.year + 1):
        for month in range(1, 13):
            is_quarter = month in ADVANCE_TAX_MONTHS
            day = pd.Timestamp(year, month, ADVANCE_TAX_DAY if is_quarter else GST_DAY)
            for k in range(-w - 1, w + 2):
                tax_days.add(pd.Timestamp(year, month, ADVANCE_TAX_DAY) + pd.Timedelta(days=k))
                tax_days.add(pd.Timestamp(year, month, GST_DAY) + pd.Timedelta(days=k))
            drop = change(day, w, w)
            if drop is None:
                continue
            (advance if is_quarter else gst).append(-drop)
            if is_quarter and drop < 0:
                for horizon in returned:
                    back = change(day + pd.Timedelta(days=w), 0, horizon)
                    if back is not None:
                        returned[horizon].append(back / -drop)
    if not advance or not gst:
        raise AnchorError("need at least one advance-tax and one GST date in the MMO history")
    steps = daily.diff().dropna()
    quiet = steps[~steps.index.isin(tax_days)]
    noise_sd = float(1.4826 * (quiet - quiet.median()).abs().median())
    cycle = TaxCycle(
        advance_tax_drain=float(np.median(advance)),
        gst_drain=float(np.median(gst)),
        returned_by_day={h: float(np.median(v)) for h, v in returned.items() if v},
        events=len(advance) + len(gst),
    )
    return cycle, noise_sd


def _reaction(frame: pd.DataFrame) -> Reaction:
    ops = frame[["vrr", "vrrr", "ell"]].copy()
    ops["ell_prev"] = ops["ell"].shift(1)
    new_vrr = ops["vrr"].diff() > 1000
    new_vrrr = ops["vrrr"].diff() > 1000
    usable = ops["ell_prev"].notna()
    x = ops.loc[usable, "ell_prev"].to_numpy()
    vrr_sizes = ops["vrr"].diff()[new_vrr]
    vrrr_sizes = ops["vrrr"].diff()[new_vrrr]
    return Reaction(
        vrr=fit_reaction(x, new_vrr[usable].to_numpy(dtype=float)),
        vrrr=fit_reaction(x, new_vrrr[usable].to_numpy(dtype=float)),
        vrr_size=float(vrr_sizes.median()),
        vrrr_size=float(vrrr_sizes.median()),
        vrr_days=int(new_vrr.sum()),
        vrrr_days=int(new_vrrr.sum()),
    )


def _tbills(
    service: DataService, frame: pd.DataFrame
) -> tuple[dict[str, float], date, dict[str, float], dict[str, float]]:
    levels: dict[str, float] = {}
    fitted: dict[str, float] = {}
    as_of: date | None = None
    for tenor in TBILL_TENORS:
        series = required_series(service, f"fbil/tbill/{tenor}") / 100
        levels[tenor] = float(series.iloc[-1])
        as_of = series.index[-1].date()
        joined = pd.DataFrame({"t": series}).join(frame[["repo", "ell"]], how="inner").dropna()
        slope, _ = np.polyfit(joined["ell"], joined["t"] - joined["repo"], 1)
        fitted[tenor] = float(slope)
    if as_of is None:  # unreachable: TBILL_TENORS is non-empty
        raise AnchorError("no T-bill tenors")
    # Adding liquidity should not raise bill yields: a positive fitted slope (12M) mixes in rate
    # expectations, so it is set to zero rather than used.
    slopes = {k: min(v, 0.0) for k, v in fitted.items()}
    return levels, as_of, slopes, fitted


def build_india_anchors(service: DataService) -> INAnchors:
    infos = {i.series_id: i.label for i in service.series_info()}
    frame = _frame(service)

    def pct(series_id: str) -> float:
        return required_latest(service, series_id)[1] / 100

    last = frame.dropna(subset=["F", "req"]).iloc[-1]
    as_of = frame.dropna(subset=["F", "req"]).index[-1].date()
    crr = pct("rbi/crr")
    days, fit = _fit_map(frame)
    deviations, excursions = _excursions(frame, days, fit.curve)
    curve = fit.curve
    latest_day = days.iloc[-1]
    predicted = float(curve.spread(latest_day["ell"]))
    wacr = frame["wacr"].dropna()
    durable_date, durable = required_latest(service, MMO + "durable_liquidity")
    weekdays = frame[(frame.index >= frame.index.max() - pd.Timedelta(days=365))]
    weekdays = _weekdays(weekdays)
    tax, noise_sd = _tax_cycle(frame)
    tbills, tbill_as_of, slopes, fitted = _tbills(service, frame)
    ndtl_series = frame["ndtl"].dropna()
    year_ago = ndtl_series[ndtl_series.index <= ndtl_series.index[-1] - pd.Timedelta(days=365)]
    growth = (
        math.log(float(ndtl_series.iloc[-1]) / float(year_ago.iloc[-1])) if len(year_ago) else 0.0
    )
    history_start = frame.index.max() - pd.Timedelta(days=365)
    recent = frame[frame.index >= history_start].dropna(subset=["wacr", "repo"])
    used = {
        sid
        for sid, label in infos.items()
        if sid.startswith(("rbi/", "fbil/tbill/", "fbil/gsec/")) and label != "MISSING"
    }
    gsec: GsecAnchors | None = None
    gsec_error: str | None = None
    try:
        gsec = build_gsec_anchors(service, frame["repo"].dropna(), tbills)
    except (AnchorError, ValueError) as exc:  # the money market runs without the curve
        gsec_error = str(exc)
    return INAnchors(
        as_of=as_of,
        repo=pct("rbi/repo"),
        sdf=pct("rbi/sdf"),
        msf=pct("rbi/msf"),
        crr=crr,
        slr=pct("rbi/slr"),
        ndtl=implied_ndtl(float(last["req"]), float(last["crr"])),
        crr_requirement=float(last["req"]),
        surplus=float(last["S"]),
        vrr_outstanding=float(last["vrr"]),
        vrrr_outstanding=float(last["vrrr"]),
        durable_liquidity=durable,
        durable_as_of=durable_date,
        wacr=float(wacr.iloc[-1]),
        wacr_as_of=wacr.index[-1].date(),
        call_volume=float(weekdays["call_volume"].median()),
        liquidity_map=curve,
        map_rmse_bp=fit.rmse_bp,
        map_points=fit.n_points,
        map_residual_ar1=fit.residual_ar1,
        map_residual=float(latest_day["wacr"] - latest_day["repo"]) - predicted,
        spreads=_segment_spreads(frame),
        tbills=tbills,
        tbill_as_of=tbill_as_of,
        tbill_slopes=slopes,
        tbill_slopes_fitted=fitted,
        tax=tax,
        noise_sd=noise_sd,
        ndtl_growth=growth,
        reaction=_reaction(frame),
        deviations=deviations,
        excursions=excursions,
        history=[
            (pd.Timestamp(d).date(), float(s))
            for d, s in zip(recent.index, recent["wacr"] - recent["repo"], strict=True)
        ],
        quality={sid: infos[sid] for sid in sorted(used)},
        gsec=gsec,
        gsec_error=gsec_error,
    )
