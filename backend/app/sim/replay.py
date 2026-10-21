"""Module D: replays of real episodes. The model is driven by what actually moved from the
episode's start, and each of its paths is set against what actually happened.

Each episode (``data/replays/<ID>/v1``: ``episode.yaml``, ``series/*.csv``, ``manifest.json``)
names its drivers and targets; a runner per episode does the driving:

* TAPER2013: the US → India chain (Phase 9) on the actual daily moves of the US 10Y and the
  VIX, against India's FPI flows, the rupee and RBI's reserves. The chain is calibrated on
  2014–2026, so 2013 is out of sample.
* GILT2022: the fire-sale price impact λ fitted to the 30-year gilt's daily moves against LDI
  funds' net forced sales (net of the Bank of England's purchases) over the market's depth,
  with the LDI profile's assumption varied. In sample, by construction.
* DASH2020: Treasuries under net selling (foreign sales less the Fed's purchases), priced by
  the gilt λ moved over by the depth ratio and by the US simulator's own impact model.
* HIKE2022: the US curve from the actual Fed path through the simulator's policy loading plus
  QT's term premium; India's WACR from repo and the actual liquidity through the macro map.
* ADVTAX: WACR through the macro map on the actual liquidity of the three worst advance-tax
  months.
"""

import itertools
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from app.sim.anchors import AnchorError
from sovereign_engine.bonds.cashflows import CashFlows, modified_duration
from sovereign_engine.india.liquidity_map import LiquidityMap
from sovereign_engine.india.rules import crr_on, in_icrr_period
from sovereign_engine.linkage import LinkParams, MarketStart, replay_chain
from sovereign_engine.rates.loadings import expectations_loading, term_premium_loading
from sovereign_engine.replay import (
    LambdaFit,
    ReplayScore,
    fit_lambda,
    move_per_unit,
    score,
    summarize,
)
from sovereign_engine.us.balance_sheet import term_premium_effect
from sovereign_engine.us.impact import BUCKET_TENORS, PriceImpactModel

VERSION = "v1"
CALENDAR_PER_BUSINESS_DAY = 7 / 5


@dataclass(frozen=True, slots=True)
class Episode:
    id: str
    title: str
    summary: str
    model: str
    start: date
    end: date
    drivers: tuple[str, ...]
    targets: tuple[str, ...]
    annotations: tuple[dict[str, str], ...]
    params: dict[str, Any]
    segments: tuple[dict[str, Any], ...]
    folder: Path
    manifest: dict[str, Any]

    def series(self, name: str) -> pd.Series:
        frame = pd.read_csv(self.folder / "series" / f"{name}.csv", parse_dates=["date"])
        return frame.set_index("date")["value"].astype(float).sort_index()


def load_episode(root: Path, episode_id: str) -> Episode:
    folder = root / episode_id.upper() / VERSION
    spec_file = folder / "episode.yaml"
    if not spec_file.exists():
        raise AnchorError(f"no replay {episode_id} in {root}")
    spec: dict[str, Any] = yaml.safe_load(spec_file.read_text("utf-8"))
    manifest: dict[str, Any] = yaml.safe_load((folder / "manifest.json").read_text("utf-8"))
    window = spec["window"]
    return Episode(
        id=spec["id"],
        title=spec["title"],
        summary=spec["summary"],
        model=spec["model"],
        start=date.fromisoformat(str(window["start"])),
        end=date.fromisoformat(str(window["end"])),
        drivers=tuple(spec.get("drivers", ())),
        targets=tuple(spec.get("targets", ())),
        annotations=tuple(
            {"date": str(n["date"]), "text": str(n["text"]), "source": str(n["source"])}
            for n in spec.get("annotations", ())
        ),
        params=dict(spec.get("params") or {}),
        segments=tuple(spec.get("segments") or ()),
        folder=folder,
        manifest=manifest.get("series", {}),
    )


def episode_ids(root: Path) -> list[str]:
    found = [p.parent.parent.name for p in root.glob(f"*/{VERSION}/episode.yaml")]
    return sorted(found, key=lambda i: load_episode(root, i).start)


@dataclass(frozen=True, slots=True)
class Line:
    name: str
    values: list[float | None]


@dataclass(frozen=True, slots=True)
class TargetResult:
    key: str
    label: str
    unit: str
    digits: int
    dates: list[str]
    actual: list[float | None]
    models: list[Line]
    scores: dict[str, ReplayScore]
    summary: list[str]


@dataclass(frozen=True, slots=True)
class ReplayResult:
    episode: Episode
    targets: list[TargetResult]
    facts: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _days(start: date, end: date) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def _on(series: pd.Series, days: pd.DatetimeIndex) -> pd.Series:
    """A series at the given days, each taking the latest value on or before it."""
    joined = series.reindex(series.index.union(days)).ffill()
    return pd.Series(joined.reindex(days).to_numpy(dtype=float), index=days)


def _clean(values: np.ndarray | pd.Series) -> list[float | None]:
    return [float(v) if math.isfinite(float(v)) else None for v in np.asarray(values, dtype=float)]


def _target(
    key: str,
    label: str,
    unit: str,
    days: pd.DatetimeIndex,
    actual: np.ndarray | pd.Series,
    models: dict[str, np.ndarray | pd.Series],
    *,
    digits: int = 1,
    horizon: int = 5,
) -> TargetResult:
    """One target's actual path and model paths, scored (direction over ``horizon`` days:
    weekly by default, so day-to-day noise does not decide it)."""
    a = np.asarray(actual, dtype=float)
    moves = "weeks that moved" if horizon == 5 else "days that moved"
    scores, summary = {}, []
    for name, path in models.items():
        s = score(np.asarray(path, dtype=float), a, horizon=horizon)
        scores[name] = s
        prefix = label if len(models) == 1 else f"{label} ({name})"
        summary += summarize(prefix, unit, s, digits=digits, moves=moves)
    return TargetResult(
        key=key,
        label=label,
        unit=unit,
        digits=digits,
        dates=[f"{d:%Y-%m-%d}" for d in days],
        actual=_clean(a),
        models=[Line(n, _clean(p)) for n, p in models.items()],
        scores=scores,
        summary=summary,
    )


# ----------------------------------------------------------------------- TAPER2013


def run_taper(ep: Episode, link: LinkParams) -> ReplayResult:
    days = _days(ep.start, ep.end)
    us = _on(ep.series("us10y"), days)
    vix = _on(ep.series("vix"), days)
    inr = _on(ep.series("inr"), days)
    reserves = _on(ep.series("reserves"), days) / 1000
    start = MarketStart(float(inr.iloc[0]), float(reserves.iloc[0]), 0.0, 1.0, 0.0)
    chain = replay_chain(
        (us.diff().fillna(0.0) * 100).to_numpy(), vix.diff().fillna(0.0).to_numpy(), start, link
    )
    flows = ep.series("fpi_total").reindex(days).fillna(0.0) / 1000
    targets = [
        _target(
            "fpi",
            "FPI flows since 1 May",
            " $bn",
            days,
            flows.cumsum(),
            {"chain": np.cumsum(chain.fpi_bn)},
            digits=2,
        ),
        _target("inr", "Rupees per dollar", "", days, inr, {"chain": chain.inr}, digits=2),
        _target("reserves", "RBI's reserves", " $bn", days, reserves, {"chain": chain.reserves_bn}),
    ]
    facts = {
        "calibration": "the chain as calibrated on 2014–2026 data (Phase 9): 2013 is out of sample",
        "us10y_change_bp": float((us.iloc[-1] - us.iloc[0]) * 100),
        "vix_change": float(vix.iloc[-1] - vix.iloc[0]),
    }
    return ReplayResult(ep, targets, facts)


# ----------------------------------------------------------------------- GILT2022


def _spread(total: float, days: list[pd.Timestamp], index: pd.DatetimeIndex) -> pd.Series:
    out = pd.Series(0.0, index=index)
    inside = [d for d in days if d in index]
    if inside:
        out[inside] = total / len(inside)
    return out


def ldi_profile(
    name: str, total: float, window: pd.DatetimeIndex, index: pd.DatetimeIndex
) -> pd.Series:
    """LDI funds' daily gilt sales (£bn) under one of the stated profiles."""
    days = [d for d in window if d in index]
    first_week = [d for d in days if d <= pd.Timestamp("2022-09-29")]
    spike = [d for d in days if pd.Timestamp("2022-09-26") <= d <= pd.Timestamp("2022-09-28")]
    if name == "even":
        return _spread(total, days, index)
    if name == "front":
        return _spread(total / 2, first_week, index) + _spread(
            total / 2, [d for d in days if d not in first_week], index
        )
    if name == "spike":
        return _spread(total / 3, spike, index) + _spread(
            2 * total / 3, [d for d in days if d not in spike], index
        )
    raise ValueError(f"unknown LDI profile {name}")


def boe_purchases(
    holdings: dict[str, float], operations: tuple[date, date], index: pd.DatetimeIndex
) -> pd.Series:
    """The Bank's daily purchases (£bn): each week's rise in holdings spread over that week's
    operation days."""
    ops = [d for d in pd.bdate_range(*operations) if d in index]
    out = pd.Series(0.0, index=index)
    marks = sorted((pd.Timestamp(k), float(v)) for k, v in holdings.items())
    for (prev_day, prev_level), (day, level) in itertools.pairwise(marks):
        week = [d for d in ops if prev_day < d <= day] or [d for d in ops if prev_day <= d <= day]
        if week:
            out[week] += (level - prev_level) / len(week)
    return out


def gilt_lambda(
    ep: Episode, profile: str = "even", *, announcements: bool = False
) -> tuple[LambdaFit, pd.Series, pd.Series]:
    """λ for one LDI profile, with the daily net sales and 30Y moves it was fitted on. The
    Bank's announcement day is left out unless ``announcements``: its move was the news, not
    a flow."""
    p = ep.params
    y30 = ep.series("gilt30y")
    index = pd.DatetimeIndex(y30.index)
    window = pd.bdate_range(str(p["ldi_window"][0]), str(p["ldi_window"][1]))
    ops = tuple(date.fromisoformat(str(d)) for d in p["boe_operation_days"])
    net = ldi_profile(profile, float(p["ldi_sales_bn"]), window, index) - boe_purchases(
        p["boe_holdings"], (ops[0], ops[1]), index
    )
    dy = y30.diff() * 100
    skip = set() if announcements else {pd.Timestamp(d) for d in p.get("announcement_days", ())}
    fit_days = [d for d in window if d in index and d not in skip]
    fit = fit_lambda(dy[fit_days].to_numpy(), net[fit_days].to_numpy(), float(p["depth_bn"]))
    return fit, net, dy


def run_gilt(ep: Episode) -> ReplayResult:
    fit, net, _ = gilt_lambda(ep)
    y30 = ep.series("gilt30y")
    days = pd.DatetimeIndex(y30.index)
    depth = float(ep.params["depth_bn"])
    model = float(y30.iloc[0]) + np.cumsum(fit.lam * net.to_numpy() / depth) / 100
    profiles = []
    for name in ep.params["ldi_profiles"]:
        for keep in (False, True):
            f, _, _ = gilt_lambda(ep, name, announcements=keep)
            profiles.append(
                {
                    "profile": name,
                    "announcement_day": keep,
                    "lam": f.lam,
                    "low": f.low,
                    "high": f.high,
                    "r2": f.r2,
                    "n": f.n,
                }
            )
    targets = [
        _target("gilt30y", "30-year gilt", "%", days, y30, {"forced selling × λ": model}, digits=2)
    ]
    facts = {
        "lambda": {
            "lam_bp": fit.lam,
            "low_bp": fit.low,
            "high_bp": fit.high,
            "level": fit.level,
            "n": fit.n,
            "r2": fit.r2,
            "alpha_bp": fit.alpha,
            "profile": "even",
            "profiles": profiles,
            "depth_bn": depth,
            "bp_per_bn_gbp": move_per_unit(fit.lam, depth),
        },
        "net_sales_bn": _clean(net),
    }
    notes = [
        "In sample: λ is fitted on the same days it is replayed on.",
        "LDI funds' daily sales are not published: the £36bn total is spread by an assumed "
        "profile; the table shows λ under each, with and without the announcement day.",
        "The Bank's announcement day (28 Sep) is left out of the base fit: its 100 bp fall was "
        "the news of the backstop, not a flow.",
    ]
    return ReplayResult(ep, targets, facts, notes)


# ----------------------------------------------------------------------- DASH2020


def run_dash(ep: Episode, gilt: Episode, impact: PriceImpactModel | None = None) -> ReplayResult:
    p = ep.params
    days = _days(ep.start, ep.end)
    selling = pd.bdate_range(str(p["selling_days"][0]), str(p["selling_days"][1]))
    foreign = _spread(float(p["foreign_sales_bn"]), list(selling), days)
    fed_levels = ep.series("fed_treasuries") / 1000  # $bn, Wednesdays
    fed = pd.Series(0.0, index=days)
    marks = list(zip(pd.DatetimeIndex(fed_levels.index), fed_levels.to_numpy(), strict=True))
    for (prev_day, prev), (day, level) in itertools.pairwise(marks):
        week = [d for d in days if prev_day < d <= day]
        if week:
            fed[week] += (level - prev) / len(week)
    net = foreign - fed
    fit, _, _ = gilt_lambda(gilt)
    depth = float(p["depth_bn"])
    debt = _on(ep.series("debt_public") / 1e9, days)
    model = impact or PriceImpactModel(reference_market=float(p["debt_public_2010_bn"]))
    targets = []
    for key, label, tenor in (("us10y", "US 10Y", 10.0), ("us30y", "US 30Y", 30.0)):
        actual = _on(ep.series(key), days)
        by_lambda = float(actual.iloc[0]) + np.cumsum(fit.lam * net.to_numpy() / depth) / 100
        # The Fed bought, and foreigners sold, across the curve: a third in each bucket.
        weight = float(np.mean([model.kernel([tenor], c)[0] for c in BUCKET_TENORS.values()]))
        decay = 2 ** (-CALENDAR_PER_BUSINESS_DAY / model.half_life_days)
        temp, cum, path = 0.0, 0.0, []
        for q, outstanding in zip(net.to_numpy(), debt.to_numpy(), strict=True):
            cum += float(q)
            scale = model.reference_market / float(outstanding)
            perm = model.permanent_bp * cum / model.reference_sale * scale * weight
            pace = float(q) / CALENDAR_PER_BUSINESS_DAY  # the reference pace is per calendar day
            size = model.temporary_bp * math.sqrt(abs(pace) / model.reference_pace)
            target = math.copysign(size, pace) * scale * weight
            temp = target + (temp - target) * decay
            path.append(float(actual.iloc[0]) + (perm + temp) / 100)
        targets.append(
            _target(
                key,
                label,
                "%",
                days,
                actual,
                {"gilt λ": by_lambda, "US impact model": np.array(path)},
                digits=2,
            )
        )
    facts = {
        "lambda_bp": fit.lam,
        "bp_per_bn": move_per_unit(fit.lam, depth),
        "depth_bn": depth,
        "foreign_sales_bn": float(p["foreign_sales_bn"]),
        "fed_purchases_bn": float(fed.sum()),
        "net_sales_bn": _clean(net),
    }
    notes = [
        "Yields also moved with news the models leave out: two emergency cuts, recession fears.",
        "The gilt λ ends near the actual 10Y through offsetting errors: it misses the rally to "
        "9 March and keeps falling through April as the Fed kept buying, while the actual 10Y "
        "held between 0.6% and 0.8%.",
        "The US impact model's buying side is its selling side mirrored (an extension for the "
        "replay: the simulator itself only sells).",
    ]
    return ReplayResult(ep, targets, facts, notes)


# ----------------------------------------------------------------------- HIKE2022


def _ndtl_surplus(net: pd.Series, requirement: pd.Series) -> pd.Series:
    """System surplus, % of NDTL (NDTL = CRR requirement ÷ CRR). While the requirement may
    include an incremental CRR, NDTL is held at its last value before: the day's liquidity
    still moves the surplus."""
    days = pd.DatetimeIndex(requirement.index)
    ndtl = requirement / np.array([crr_on(d.date()) for d in days])
    ndtl[np.array([in_icrr_period(d.date()) for d in days])] = np.nan
    joined = pd.DataFrame({"net": net, "ndtl": ndtl.ffill()}).sort_index()
    return -joined["net"] / joined["ndtl"] * 100


def _ten_year_duration(yield_pct: float) -> float:
    return float(modified_duration(CashFlows.bullet(yield_pct / 100, 20), yield_pct / 100, 2))


def run_hike(
    ep: Episode,
    liquidity_map: LiquidityMap,
    *,
    passthrough: float = 0.5,
    tp_scale: float = 7.0,
    treasury_duration: float = 6.0,
    mbs_duration: float = 5.5,
) -> ReplayResult:
    days = _days(ep.start, ep.end)
    target = _on(ep.series("fed_target"), days)
    policy = (target - float(target.iloc[0])) / 100
    treasuries = _on(ep.series("fed_treasuries"), days) / 1000
    mbs = _on(ep.series("fed_mbs"), days) / 1000
    gdp = _on(ep.series("gdp"), days)
    us10 = _on(ep.series("us10y"), days)
    d10 = _ten_year_duration(float(us10.iloc[0]))
    runoff = (float(treasuries.iloc[0]) - treasuries) * treasury_duration / d10 + (
        float(mbs.iloc[0]) - mbs
    ) * mbs_duration / d10
    tp = np.array(
        [term_premium_effect(float(r), float(g)) for r, g in zip(runoff, gdp, strict=True)]
    )
    targets = []
    for key, label, tenor in (("us2y", "US 2Y", 2.0), ("us10y", "US 10Y", 10.0)):
        actual = _on(ep.series(key), days)
        a = float(expectations_loading([tenor], passthrough)[0])
        t = float(term_premium_loading([tenor], tp_scale)[0])
        model = float(actual.iloc[0]) + (policy.to_numpy() * a + tp * t) * 100
        targets.append(_target(key, label, "%", days, actual, {"policy + QT": model}, digits=2))
    repo = _on(ep.series("repo"), days) / 100
    surplus = _on(_ndtl_surplus(ep.series("net_liquidity"), ep.series("crr_requirement")), days)
    wacr = ep.series("wacr")
    wacr_days = pd.DatetimeIndex([d for d in days if d in wacr.index])
    model_wacr = (repo[wacr_days] + liquidity_map.spread(surplus[wacr_days].to_numpy())) * 100
    targets.append(
        _target(
            "wacr",
            "India's WACR",
            "%",
            wacr_days,
            wacr[wacr_days],
            {"repo + map": model_wacr},
            digits=2,
        )
    )
    facts = {
        "policy_passthrough": passthrough,
        "fed_change_bp": float(policy.iloc[-1] * 1e4),
        "qt_10ye_bn": float(runoff.iloc[-1]),
        "qt_term_premium_bp": float(tp[-1] * 1e4),
    }
    notes = [
        "The macro map was fitted on April 2022 – October 2026, so India's WACR is in sample.",
        "Inflation expectations and the term premium's other moves are not in the US model.",
    ]
    return ReplayResult(ep, targets, facts, notes)


# ----------------------------------------------------------------------- ADVTAX


def run_advtax(ep: Episode, liquidity_map: LiquidityMap) -> ReplayResult:
    wacr = ep.series("wacr")
    repo = ep.series("repo") / 100
    surplus = _ndtl_surplus(ep.series("net_liquidity"), ep.series("crr_requirement"))
    days = pd.DatetimeIndex(wacr.index)
    model = (_on(repo, days) + liquidity_map.spread(_on(surplus, days).to_numpy())) * 100
    targets = [_target("wacr", "WACR", "%", days, wacr, {"repo + map": model}, digits=2, horizon=1)]
    per_segment = []
    for s in ep.segments:
        inside = (days >= pd.Timestamp(s["start"])) & (days <= pd.Timestamp(s["end"]))
        sc = score(model[inside].to_numpy(), wacr[inside].to_numpy())  # day by day
        per_segment.append({**s, "rmse_bp": sc.rmse * 100, "direction": sc.direction})
    facts = {"segments": per_segment}
    notes = [
        "The macro map was fitted on the same data (in sample): this shows how much of each "
        "squeeze the liquidity map explains, and what it leaves to the day's own deviations.",
        "While the reported requirement may include the incremental CRR (10 Aug – 20 Oct 2023), "
        "NDTL is held at its last value before it.",
    ]
    return ReplayResult(ep, targets, facts, notes)


# ----------------------------------------------------------------------- the panel


def _score_dict(s: ReplayScore) -> dict[str, Any]:
    return {
        "n": s.n,
        "rmse": s.rmse,
        "mae": s.mae,
        "direction": s.direction,
        "peak_model": s.peak_model,
        "peak_actual": s.peak_actual,
        "peak_lag": s.peak_lag,
        "end_model": s.end_model,
        "end_actual": s.end_actual,
    }


def replay_panel(result: ReplayResult, available: list[dict[str, str]]) -> dict[str, Any]:
    ep = result.episode
    return {
        "episode": {
            "id": ep.id,
            "title": ep.title,
            "summary": ep.summary,
            "start": ep.start.isoformat(),
            "end": ep.end.isoformat(),
            "segments": list(ep.segments),
            "sources": {name: entry.get("url") for name, entry in ep.manifest.items()},
        },
        "annotations": list(ep.annotations),
        "targets": [
            {
                "key": t.key,
                "label": t.label,
                "unit": t.unit,
                "digits": t.digits,
                "dates": t.dates,
                "actual": t.actual,
                "models": [{"name": m.name, "values": m.values} for m in t.models],
                "scores": {name: _score_dict(s) for name, s in t.scores.items()},
                "summary": t.summary,
            }
            for t in result.targets
        ],
        "facts": result.facts,
        "notes": result.notes,
        "available": available,
    }
