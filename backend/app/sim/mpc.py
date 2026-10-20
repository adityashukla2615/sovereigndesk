"""The MPC predictor: RBI's repo decisions since April 2014, what was known before each, three
models, a walk-forward backtest, and a forecast for the next scheduled meeting.

Each decision's features use only information public by the day before it:

* CPI inflation (MoSPI's published year-on-year rate) and core inflation (excluding food and
  beverages, and fuel) for the latest month released: MoSPI releases a month's CPI on the 12th
  of the next. Base 2012 through Dec 2025, base 2024 from Jan 2026. MoSPI does not publish the
  weights with the indices, so they are recovered from the indices themselves.
* Real GDP growth for the latest quarter released (about two months after it ends; base 2011-12,
  then 2022-23), and the output gap from a one-sided HP filter on real GDP over four quarters
  (which removes the seasonal pattern of India's unadjusted quarterly GDP).
* WACR − repo and system liquidity (% of NDTL, surplus positive), averaged over the two weeks
  before the decision; the latest 91-day T-bill cut-off − repo.
* The US federal funds rate and its three-month change; the rupee's three-month change against
  the dollar; whether the decision is the MPC's (from October 2016); and the previous decision.

Later revisions of CPI and GDP are not undone: the values used are today's, not the first
prints.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.data.service import DataService
from app.sim.anchors import AnchorError, required_series
from sovereign_engine._types import ArrayLike, FloatArray, IntArray
from sovereign_engine.india.rules import crr_on, in_icrr_period
from sovereign_engine.predict import (
    CLASSES,
    Backtest,
    BoostedClassifier,
    OrderedLogit,
    TaylorBaseline,
    TaylorRule,
    component_weights,
    decision_class,
    exclusion_index,
    fit_boosted,
    fit_ordered_logit,
    hp_one_sided,
    walk_forward,
)

FEATURES: tuple[str, ...] = (
    "cpi", "core", "wacr_spread", "tbill_spread", "liquidity", "gdp", "fed_funds", "fed_change",
    "inr_change", "regime", "last_change",
)  # fmt: skip
FEATURE_LABELS: dict[str, str] = {
    "cpi": "CPI inflation, y/y (%)",
    "core": "Core CPI inflation, y/y (%)",
    "wacr_spread": "WACR − repo, two weeks (bp)",
    "tbill_spread": "91-day T-bill − repo (bp)",
    "liquidity": "System liquidity, two weeks (% of NDTL)",
    "gdp": "Real GDP growth, y/y (%)",
    "fed_funds": "US federal funds rate (%)",
    "fed_change": "Fed funds, 3-month change (bp)",
    "inr_change": "INR per USD, 3-month change (%)",
    "regime": "MPC era (1) or Governor (0)",
    "last_change": "Previous decision (bp)",
}
MMO_DAILY_FROM = date(2022, 4, 8)
"""From this date the daily Money Market Operations series hold the money markets; before it,
the readings fetched around each decision."""
CPI_2024_FROM = date(2026, 1, 1)
"""The first month of the 2024-base CPI series."""


@dataclass(frozen=True, slots=True)
class MpcParams:
    """Settings that are assumptions or policy values (listed in ASSUMPTIONS.md)."""

    # VERIFY: RBI's estimates of the neutral real rate: 1.6-1.8% (Q4 2014-15) and 0.8-1.0%
    # (Q3 2021-22), RBI Bulletin "Revisiting India's Natural Rate of Interest" (16 Jun 2022);
    # 1.4-1.9% (Q4 2023-24) in the July 2024 update as reported. Checked 2026-10-20.
    r_star: float = 0.015
    # VERIFY: the inflation target, 4% with a 2-6% band, notified under section 45ZA of the RBI
    # Act for 2016-21, 2021-26 and 2026-31 (gazette of 25 Mar 2026, as reported). Checked
    # 2026-10-20 against the MPC resolution of 8 Jun 2023.
    pi_star: float = 0.04
    window_days: int = 14
    l2: float = 1.0
    backtest_start: int = 24
    hp_lambda: float = 1600.0
    mpc_from: date = date(2016, 10, 4)


@dataclass(frozen=True, slots=True)
class CoreWeights:
    base: str
    excluded: dict[str, float]
    """Recovered weights of the excluded components (shares of the total)."""
    all_weights: dict[str, float]
    rmse: float
    """How closely the weights rebuild the general index (index points)."""
    months: int


@dataclass(frozen=True, slots=True)
class MacroInputs:
    cpi: pd.Series
    """Headline CPI inflation by month (%), dated the month's first day."""
    core: pd.Series
    gdp_growth: pd.Series
    """Real GDP growth by quarter (%), dated the quarter's first day."""
    output_gap: pd.Series
    """One-sided HP output gap (fraction of potential) by quarter."""
    fed: pd.Series
    inr: pd.Series
    wacr: pd.Series
    surplus_pct: pd.Series
    """System surplus (−net liquidity injected) as % of NDTL, daily."""
    tbill: pd.Series
    repo: pd.Series
    """The repo rate after each decision (%), dated the decision."""
    weights: tuple[CoreWeights, ...]


def _yoy(index: pd.Series) -> pd.Series:
    monthly = index.sort_index()
    previous = monthly.shift(12, freq="MS")
    return (monthly / previous.reindex(monthly.index) - 1) * 100


def _core(service: DataService) -> tuple[pd.Series, tuple[CoreWeights, ...]]:
    groups_2012 = (
        "general", "food_beverages", "pan_tobacco", "clothing_footwear", "housing",
        "fuel_light", "miscellaneous",
    )  # fmt: skip
    old = pd.DataFrame({g: required_series(service, f"mospi/cpi/2012/{g}") for g in groups_2012})
    old = old.dropna()
    parts = old[list(groups_2012[1:])]
    w_old, rmse_old = component_weights(old["general"].to_numpy(), parts.to_numpy())
    named_old = dict(zip(groups_2012[1:], (float(w) for w in w_old), strict=True))
    excluded_old = {k: named_old[k] for k in ("food_beverages", "fuel_light")}
    core_old = pd.Series(
        exclusion_index(
            old["general"].to_numpy(),
            old[list(excluded_old)].to_numpy(),
            np.array(list(excluded_old.values())),
        ),
        index=old.index,
    )
    divisions = ("cp01", "cp02", "cp03", "cp04", "cp05", "cp06", "cp07", "cp08", "cp09",
                 "cp10", "cp11", "cp13")  # fmt: skip
    groups_04 = ("cp04_1", "cp04_3", "cp04_4", "cp04_5")
    codes = ("cp00", *divisions, *groups_04)
    new = pd.DataFrame({c: required_series(service, f"mospi/cpi/2024/{c}") for c in codes})
    new = new.dropna()
    w_new, rmse_new = component_weights(new["cp00"].to_numpy(), new[list(divisions)].to_numpy())
    named_new = dict(zip(divisions, (float(w) for w in w_new), strict=True))
    w_04, _ = component_weights(new["cp04"].to_numpy(), new[list(groups_04)].to_numpy())
    fuel = named_new["cp04"] * float(w_04[groups_04.index("cp04_5")])
    excluded_new = {"cp01": named_new["cp01"], "cp04_5": fuel}
    core_new = pd.Series(
        exclusion_index(
            new["cp00"].to_numpy(),
            new[["cp01", "cp04_5"]].to_numpy(),
            np.array([excluded_new["cp01"], fuel]),
        ),
        index=new.index,
    )
    core = pd.concat(
        [_yoy(core_old).loc[: pd.Timestamp(CPI_2024_FROM) - pd.Timedelta(days=1)],
         _yoy(core_new).loc[pd.Timestamp(CPI_2024_FROM) :]]
    ).dropna()  # fmt: skip
    weights = (
        CoreWeights("2012", excluded_old, named_old, rmse_old, len(old)),
        CoreWeights("2024", excluded_new, named_new | {"cp04_5": fuel}, rmse_new, len(new)),
    )
    return core, weights


def _gdp(service: DataService, lam: float) -> tuple[pd.Series, pd.Series]:
    growth_old = required_series(service, "mospi/gdp/2011/real_growth")
    growth_new = required_series(service, "mospi/gdp/2022/real_growth")
    last_old = growth_old.index.max()
    growth = pd.concat([growth_old, growth_new[growth_new.index > last_old]]).sort_index()
    level_old = required_series(service, "mospi/gdp/2011/real")
    level_new = required_series(service, "mospi/gdp/2022/real")
    overlap = level_old.index.intersection(level_new.index)
    if overlap.empty:
        raise AnchorError("the two GDP bases do not overlap, so they cannot be spliced")
    ratio = float((level_new[overlap] / level_old[overlap]).mean())
    level = pd.concat([level_old[level_old.index < level_new.index.min()] * ratio, level_new])
    annual = np.log(level.sort_index().rolling(4).sum().dropna())
    trend = hp_one_sided(annual.to_numpy(), lam, min_obs=12)
    gap = pd.Series(annual.to_numpy() - trend, index=annual.index).dropna()
    return growth, gap


def _union(service: DataService, old: str, new: str) -> pd.Series:
    early = required_series(service, old)
    late = required_series(service, new)
    early = early[early.index < pd.Timestamp(MMO_DAILY_FROM)]
    late = late[late.index >= pd.Timestamp(MMO_DAILY_FROM)]
    return pd.Series(pd.concat([early, late]).sort_index())


def _points(series: pd.Series) -> list[tuple[pd.Timestamp, float]]:
    return list(zip(pd.DatetimeIndex(series.index), series.to_numpy(dtype=float), strict=True))


def build_inputs(service: DataService, params: MpcParams) -> MacroInputs:
    cpi = pd.concat(
        [
            required_series(service, "mospi/cpi/2012/general_yoy").loc[
                : pd.Timestamp(CPI_2024_FROM) - pd.Timedelta(days=1)
            ],
            required_series(service, "mospi/cpi/2024/general_yoy").loc[
                pd.Timestamp(CPI_2024_FROM) :
            ],
        ]
    ).sort_index()
    core, weights = _core(service)
    growth, gap = _gdp(service, params.hp_lambda)
    net = _union(service, "rbi/hist/net_liquidity", "rbi/mmo/net_liquidity")
    requirement = _union(service, "rbi/hist/crr_requirement", "rbi/mmo/crr_requirement")
    days = pd.DatetimeIndex(requirement.index)
    ndtl = requirement / np.array([crr_on(d.date()) for d in days])
    ndtl[np.array([in_icrr_period(d.date()) for d in days])] = np.nan
    ndtl = ndtl.ffill()
    joined = pd.DataFrame({"net": net, "ndtl": ndtl}).sort_index()
    joined["ndtl"] = joined["ndtl"].ffill()
    surplus = (-joined["net"] / joined["ndtl"] * 100).dropna()
    return MacroInputs(
        cpi=cpi.dropna(),
        core=core,
        gdp_growth=growth.dropna(),
        output_gap=gap,
        fed=required_series(service, "fred/DFF").dropna(),
        inr=required_series(service, "fred/DEXINUS").dropna(),
        wacr=_union(service, "rbi/hist/wacr", "rbi/mmo/wacr").dropna(),
        surplus_pct=surplus,
        tbill=required_series(service, "rbi/tbill91/cutoff").dropna(),
        repo=required_series(service, "rbi/mpc/repo").dropna().sort_index(),
        weights=weights,
    )


def _last_before(series: pd.Series, day: date) -> tuple[date, float] | None:
    earlier = series[series.index < pd.Timestamp(day)]
    if earlier.empty:
        return None
    return earlier.index[-1].date(), float(earlier.iloc[-1])


def _month_released(month: pd.Timestamp, day: date) -> bool:
    """MoSPI releases a month's CPI on the 12th of the next."""
    following = month + pd.offsets.MonthBegin(1)
    return day > date(following.year, following.month, 12)


def _quarter_released(quarter: pd.Timestamp, day: date) -> bool:
    """MoSPI releases a quarter's GDP by the end of the second month after it ends."""
    release = quarter + pd.offsets.MonthBegin(5)  # the first day of the third month after
    return day >= release.date()


def repo_on(inputs: MacroInputs, day: date) -> float:
    """The repo rate (decimal) in force on a day: the last decision on or before it."""
    known = inputs.repo[inputs.repo.index <= pd.Timestamp(day)]
    if known.empty:
        raise AnchorError(f"no repo decision on record by {day}")
    return float(known.iloc[-1]) / 100


def features_at(
    inputs: MacroInputs,
    day: date,
    *,
    params: MpcParams,
    last_change_bp: float,
    overrides: dict[str, float] | None = None,
) -> tuple[dict[str, float], float]:
    """The features as known the day before ``day``, and the output gap (fraction)."""
    nan = math.nan
    cpi = [v for m, v in _points(inputs.cpi) if _month_released(m, day)]
    core = [v for m, v in _points(inputs.core) if _month_released(m, day)]
    growth = [v for q, v in _points(inputs.gdp_growth) if _quarter_released(q, day)]
    gap = [v for q, v in _points(inputs.output_gap) if _quarter_released(q, day)]
    start = pd.Timestamp(day - timedelta(days=params.window_days))
    end = pd.Timestamp(day)
    wacr = inputs.wacr[(inputs.wacr.index >= start) & (inputs.wacr.index < end)]
    wacr = wacr[pd.DatetimeIndex(wacr.index).dayofweek < 5]
    spread = [(v - 100 * repo_on(inputs, t.date())) * 100 for t, v in _points(wacr)]
    surplus = inputs.surplus_pct[
        (inputs.surplus_pct.index >= start) & (inputs.surplus_pct.index < end)
    ]
    bill = _last_before(inputs.tbill, day)
    fed_now = _last_before(inputs.fed, day)
    fed_then = _last_before(inputs.fed, day - timedelta(days=91))
    inr_now = _last_before(inputs.inr, day)
    inr_then = _last_before(inputs.inr, day - timedelta(days=91))
    values = {
        "cpi": cpi[-1] if cpi else nan,
        "core": core[-1] if core else nan,
        "wacr_spread": float(np.mean(spread)) if spread else nan,
        "tbill_spread": (bill[1] - 100 * repo_on(inputs, bill[0])) * 100 if bill else nan,
        "liquidity": float(surplus.mean()) if not surplus.empty else nan,
        "gdp": growth[-1] if growth else nan,
        "fed_funds": fed_now[1] if fed_now else nan,
        "fed_change": (fed_now[1] - fed_then[1]) * 100 if fed_now and fed_then else nan,
        "inr_change": (inr_now[1] / inr_then[1] - 1) * 100 if inr_now and inr_then else nan,
        "regime": 1.0 if day >= params.mpc_from else 0.0,
        "last_change": last_change_bp,
    }
    values |= overrides or {}
    return values, (gap[-1] if gap else nan)


@dataclass(frozen=True, slots=True)
class MpcDataset:
    dates: tuple[date, ...]
    scheduled: tuple[bool, ...]
    repo_before: FloatArray
    repo_after: FloatArray
    classes: IntArray
    features: FloatArray
    output_gap: FloatArray
    """Fraction of potential, from the one-sided filter."""

    @property
    def change(self) -> FloatArray:
        return np.asarray(self.repo_after - self.repo_before, dtype=np.float64)


def build_dataset(inputs: MacroInputs, scheduled: pd.Series, params: MpcParams) -> MpcDataset:
    """One row per decision after the first: its features, class and repo before and after."""
    repo = inputs.repo
    if len(repo) < params.backtest_start + 5:
        raise AnchorError(f"only {len(repo)} policy decisions on record")
    rows: list[dict[str, float]] = []
    gaps: list[float] = []
    dates: list[date] = []
    flags: list[bool] = []
    before: list[float] = []
    after: list[float] = []
    previous_change = math.nan
    for i in range(1, len(repo)):
        day = repo.index[i].date()
        values, gap = features_at(inputs, day, params=params, last_change_bp=previous_change)
        rows.append(values)
        gaps.append(gap)
        dates.append(day)
        flags.append(bool(scheduled.get(repo.index[i], 1.0) >= 0.5))
        before.append(float(repo.iloc[i - 1]) / 100)
        after.append(float(repo.iloc[i]) / 100)
        previous_change = (after[-1] - before[-1]) * 1e4
    features = np.array([[row[f] for f in FEATURES] for row in rows])
    repo_before, repo_after = np.array(before), np.array(after)
    return MpcDataset(
        dates=tuple(dates),
        scheduled=tuple(flags),
        repo_before=repo_before,
        repo_after=repo_after,
        classes=decision_class(repo_after - repo_before),
        features=features,
        output_gap=np.array(gaps),
    )


class _Columns:
    """A predictor that reads only some columns of a wider feature matrix."""

    def __init__(self, inner: Any, columns: slice) -> None:
        self.inner, self.columns = inner, columns

    def predict_proba(self, features: ArrayLike) -> FloatArray:
        return np.asarray(
            self.inner.predict_proba(np.atleast_2d(np.asarray(features))[:, self.columns]),
            dtype=np.float64,
        )


class _Taylor:
    """The Taylor baseline as a backtest predictor, reading repo, CPI and the gap columns."""

    def __init__(self, baseline: TaylorBaseline, k: int) -> None:
        self.baseline, self.k = baseline, k

    def predict_proba(self, features: ArrayLike) -> FloatArray:
        x = np.atleast_2d(np.asarray(features, dtype=np.float64))
        cpi = np.nan_to_num(x[:, FEATURES.index("cpi")] / 100, nan=0.04)
        gap = np.nan_to_num(x[:, self.k + 1], nan=0.0)
        return self.baseline.predict_proba(x[:, self.k], cpi, gap)


@dataclass(frozen=True, slots=True)
class MpcModel:
    params: MpcParams
    inputs: MacroInputs
    dataset: MpcDataset
    logit: OrderedLogit
    boosted: BoostedClassifier
    taylor: TaylorBaseline
    backtest: Backtest
    meetings: tuple[date, ...] = field(default_factory=tuple)

    def forecast(
        self, features: dict[str, float], repo: float, output_gap: float
    ) -> dict[str, list[float]]:
        """Class probabilities from each model for one set of features."""
        x = np.array([[features[f] for f in FEATURES]])
        cpi = features["cpi"] / 100 if math.isfinite(features["cpi"]) else self.params.pi_star
        gap = output_gap if math.isfinite(output_gap) else 0.0
        return {
            "ordered logit": [float(p) for p in self.logit.predict_proba(x)[0]],
            "xgboost": [float(p) for p in self.boosted.predict_proba(x)[0]],
            "taylor": [float(p) for p in self.taylor.predict_proba(repo, cpi, gap)[0]],
        }

    def next_meeting(self, today: date) -> date | None:
        upcoming = [d for d in self.meetings if d >= today]
        return min(upcoming) if upcoming else None


def build_mpc(service: DataService, params: MpcParams | None = None) -> MpcModel:
    """The predictor fitted on the stored data (a few seconds: the backtest refits every model
    once per decision)."""
    p = params or MpcParams()
    inputs = build_inputs(service, p)
    scheduled = required_series(service, "rbi/mpc/scheduled")
    try:
        meetings = required_series(service, "rbi/mpc/meeting")
        days = tuple(d.date() for d in pd.DatetimeIndex(meetings.index))
    except AnchorError:
        days = ()
    return fit_mpc(inputs, scheduled, days, p)


def fit_mpc(
    inputs: MacroInputs, scheduled: pd.Series, meetings: tuple[date, ...], p: MpcParams
) -> MpcModel:
    data = build_dataset(inputs, scheduled, p)
    k = len(FEATURES)
    wide = np.column_stack((data.features, data.repo_before, data.output_gap))
    taylor = TaylorBaseline(TaylorRule(r_star=p.r_star, pi_star=p.pi_star))

    def logit(x: FloatArray, y: IntArray) -> _Columns:
        return _Columns(fit_ordered_logit(x[:, :k], y, l2=p.l2), slice(0, k))

    def boosted(x: FloatArray, y: IntArray) -> _Columns:
        return _Columns(fit_boosted(x[:, :k], y), slice(0, k))

    def rule(x: FloatArray, y: IntArray) -> _Taylor:
        return _Taylor(taylor, k)

    fitters: dict[str, Callable[[FloatArray, IntArray], Any]] = {
        "ordered logit": logit,
        "xgboost": boosted,
        "taylor": rule,
    }
    backtest = walk_forward(wide, data.classes, fitters, start=p.backtest_start)
    return MpcModel(
        params=p,
        inputs=inputs,
        dataset=data,
        logit=fit_ordered_logit(data.features, data.classes, l2=p.l2),
        boosted=fit_boosted(data.features, data.classes),
        taylor=taylor,
        backtest=backtest,
        meetings=meetings,
    )


def _clean(value: float) -> float | None:
    return value if math.isfinite(value) else None


def mpc_panel(
    model: MpcModel,
    *,
    day: date,
    repo_now: float,
    last_change_bp: float,
    overrides: dict[str, float],
) -> dict[str, Any]:
    """The MPC panel: today's forecast for the next meeting, the backtest and the sample."""
    data = model.dataset
    features, gap = features_at(
        model.inputs, day, params=model.params, last_change_bp=last_change_bp, overrides=overrides
    )
    probabilities = model.forecast(features, repo_now, gap)
    cpi = features["cpi"] / 100 if math.isfinite(features["cpi"]) else model.params.pi_star
    prescribed = float(model.taylor.rule.prescribed(cpi, gap if math.isfinite(gap) else 0.0))
    bt = model.backtest
    reports = {
        name: {
            "accuracy": r.accuracy,
            "macro_f1": r.macro_f1,
            "brier": r.brier,
            "confusion": r.confusion.tolist(),
        }
        for name, r in bt.reports.items()
    }
    recent = []
    for i, row in enumerate(bt.rows[-12:].tolist()):
        j = len(bt.rows) - min(12, len(bt.rows)) + i
        actual = int(bt.actual[j])
        recent.append(
            {
                "date": data.dates[row].isoformat(),
                "scheduled": data.scheduled[row],
                "change_bp": round(float(data.change[row]) * 1e4, 1),
                "actual": actual,
                "predicted": {n: int(r.predicted[j]) for n, r in bt.reports.items()},
                "p_actual": {
                    n: float(r.probabilities[j, actual])
                    for n, r in bt.reports.items()
                    if n in probabilities
                },
            }
        )
    last = {f: _clean(float(v)) for f, v in zip(FEATURES, data.features[-1], strict=True)}
    nxt = model.next_meeting(day)
    return {
        "classes": list(CLASSES),
        "as_of": day.isoformat(),
        "next_meeting": nxt.isoformat() if nxt else None,
        "probabilities": probabilities,
        "features": [
            {"key": f, "label": FEATURE_LABELS[f], "now": _clean(features[f]), "last": last[f]}
            for f in FEATURES
        ],
        "taylor": {
            "prescribed": prescribed,
            "repo": repo_now,
            "inflation": cpi,
            "output_gap": _clean(gap),
            "r_star": model.params.r_star,
            "pi_star": model.params.pi_star,
        },
        "backtest": {
            "first": data.dates[int(bt.rows[0])].isoformat(),
            "forecasts": int(bt.rows.size),
            "models": reports,
            "recent": recent,
        },
        "sample": {
            "first": data.dates[0].isoformat(),
            "last": data.dates[-1].isoformat(),
            "decisions": len(data.dates),
            "counts": np.bincount(data.classes, minlength=5).tolist(),
            "off_cycle": sum(1 for s in data.scheduled if not s),
        },
        "core_weights": [
            {"base": w.base, "excluded": w.excluded, "rmse": w.rmse, "months": w.months}
            for w in model.inputs.weights
        ],
    }
