"""Starting values for the US simulation, taken from the latest real data.

Nothing here is invented: every number comes from a stored series (with its quality tag) or is
fitted to stored history. If an input is missing the build fails loudly rather than guess.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from app.data.catalog import TREASURY_TENORS
from app.data.service import DataService
from app.data.sources.fiscaldata import MspdRow
from sovereign_engine.curves.bootstrap import bootstrap_par_yields
from sovereign_engine.curves.nss import NelsonSiegelSvensson, fit_nss
from sovereign_engine.us.balance_sheet import FedBalanceSheet, QTPlan
from sovereign_engine.us.corridor import FedCorridor, ReserveDemandCurve, fit_reserve_demand
from sovereign_engine.us.debt import DebtSecurity, IssuanceMix, Kind

TENOR_YEARS: dict[str, float] = {
    "1M": 1 / 12, "6W": 1.5 / 12, "2M": 2 / 12, "3M": 0.25, "4M": 4 / 12, "6M": 0.5,
    "1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7, "10Y": 10, "20Y": 20, "30Y": 30,
}  # fmt: skip

RESERVE_FIT_START = date(2017, 1, 1)
"""Covers abundant reserves (2017–18, 2021–), the 2019 scarcity episode and the 2022– runoff."""


class AnchorError(RuntimeError):
    """A required input series is missing."""


@dataclass(frozen=True, slots=True)
class USAnchors:
    as_of: date
    corridor: FedCorridor
    effr: float
    par_curve: dict[str, float]
    """Treasury par yields (decimals) by tenor label."""
    zero_curve: NelsonSiegelSvensson
    """NSS fitted to the bootstrapped par curve: the simulator's initial term structure."""
    term_premium: float
    """Kim–Wright 10-year term premium (decimal)."""
    balance_sheet: FedBalanceSheet
    bank_assets: float
    """USD bn, all commercial banks."""
    observed_qt: QTPlan
    """Runoff pace implied by the last 13 weeks of H.4.1 holdings (USD bn per month)."""
    reserve_curve: ReserveDemandCurve
    reserve_fit_rmse_bp: float
    dollar_index: float
    foreign_holdings: dict[str, float]
    """TIC holdings (USD bn) by country label, latest month."""
    tic_as_of: date
    debt_public: float
    """Treasury debt held by the public, USD bn."""
    debt_public_2010: float
    """Debt held by the public at the end of June 2010 (price-impact calibration reference)."""
    nominal_gdp: float
    receipts_12m: float
    deficit_12m: float
    ladder: list[DebtSecurity]
    issuance_mix: IssuanceMix
    mspd_as_of: date
    quality: dict[str, str]
    """Badge label of every input series, for the STALE/SEED indicators."""


def required_series(service: DataService, series_id: str, start: date | None = None) -> pd.Series:
    view = service.series(series_id, start=start)
    if view is None or not view.values:
        raise AnchorError(f"required series {series_id} has no data")
    return pd.Series(view.values, index=pd.to_datetime(view.dates), name=series_id)


def required_latest(service: DataService, series_id: str) -> tuple[date, float]:
    values = service.latest_values([series_id])
    if series_id not in values:
        raise AnchorError(f"required series {series_id} has no data")
    return values[series_id]


def _fit_reserve_curve(service: DataService) -> tuple[ReserveDemandCurve, float]:
    """Weekly EFFR − IORB (IOER before 29 Jul 2021) against reserves / bank assets."""
    reserves = required_series(service, "fred/WRESBAL", RESERVE_FIT_START) / 1000
    assets = required_series(service, "fred/TLAACBW027SBOG", RESERVE_FIT_START)
    effr = required_series(service, "fred/EFFR", RESERVE_FIT_START) / 100
    admin = (
        pd.concat(
            [
                required_series(service, "fred/IOER", RESERVE_FIT_START),
                required_series(service, "fred/IORB"),
            ]
        ).sort_index()
        / 100
    )
    admin = admin[~admin.index.duplicated(keep="last")]
    spread = (effr - admin.reindex(effr.index).ffill()).dropna().resample("W-WED").mean()
    ratio = reserves / assets.reindex(reserves.index).ffill()
    table = pd.DataFrame({"ratio": ratio, "spread": spread}).dropna()
    fit = fit_reserve_demand(table["ratio"].to_numpy(), table["spread"].to_numpy())
    return fit.curve, fit.rmse_bp


def _observed_runoff(service: DataService, series_id: str) -> float:
    """USD bn per month by which holdings fell over the last 13 weeks (0 if they rose)."""
    held = required_series(service, series_id) / 1000
    recent = held[held.index >= held.index[-1] - pd.Timedelta(weeks=13)]
    months = float((recent.index[-1] - recent.index[0]).days) / (365.25 / 12)
    if len(recent) < 2 or months <= 0:
        return 0.0
    return max(0.0, float(recent.iloc[0] - recent.iloc[-1]) / months)


_KINDS: dict[str, Kind] = {
    "Bills Maturity Value": "bill",
    "Notes": "note",
    "Bonds": "bond",
    "Inflation-Protected Securities": "tips",
    "Floating Rate Notes": "frn",
}


def ladder_from_mspd(rows: list[MspdRow]) -> tuple[list[DebtSecurity], IssuanceMix]:
    """One security per CUSIP: outstanding from its first row, term from its first issue."""
    by_cusip: dict[str, list[MspdRow]] = defaultdict(list)
    for row in rows:
        by_cusip[row.cusip].append(row)
    ladder: list[DebtSecurity] = []
    stock: dict[float, float] = defaultdict(float)
    for issues in by_cusip.values():
        kind = _KINDS.get(issues[0].security_class)
        outstanding = sum(r.outstanding_musd or 0.0 for r in issues) / 1000
        if kind is None or outstanding <= 0:
            continue
        first = min(issues, key=lambda r: r.issue_date)
        term = max((first.maturity_date - first.issue_date).days / 365.25, 1 / 52)
        # Interest accrues at the yield at issue (discount or premium amortises), so weight each
        # issue's yield by the amount issued; fall back to the coupon where no yield is shown.
        priced = [(r.yield_pct, r.issued_musd) for r in issues if r.yield_pct and r.issued_musd]
        if priced:
            rate = float(np.average([y for y, _ in priced], weights=[w for _, w in priced])) / 100
        else:
            rate = (first.interest_rate_pct or 0.0) / 100
        ladder.append(DebtSecurity(kind, first.maturity_date, rate, outstanding, round(term, 3)))
        stock[round(term * 4) / 4 if term >= 1 else round(term, 3)] += outstanding
    return ladder, IssuanceMix.from_stock(stock)


def build_us_anchors(service: DataService) -> USAnchors:
    infos = {i.series_id: i.label for i in service.series_info()}

    def pct(series_id: str) -> float:
        return required_latest(service, series_id)[1] / 100

    par: dict[str, float] = {}
    for tenor in TREASURY_TENORS.values():
        par[tenor] = required_latest(service, f"ust/par/{tenor}")[1] / 100
    as_of = required_latest(service, "ust/par/10Y")[0]
    tenors = np.array([TENOR_YEARS[t] for t in par])
    order = np.argsort(tenors)
    discount = bootstrap_par_yields(tenors[order], np.array(list(par.values()))[order])
    grid = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 25, 30.0])
    zero_curve = fit_nss(grid, discount.zero_rate(grid)).curve

    sheet = FedBalanceSheet.from_h41(
        total_assets=required_latest(service, "fred/WALCL")[1] / 1000,
        treasuries=required_latest(service, "fred/TREAST")[1] / 1000,
        mbs=required_latest(service, "fred/WSHOMCB")[1] / 1000,
        reserves=required_latest(service, "fred/WRESBAL")[1] / 1000,
        on_rrp=required_latest(service, "fred/RRPONTSYD")[1],
        tga=required_latest(service, "fred/WTREGEN")[1] / 1000,
        currency=required_latest(service, "fred/WCURCIR")[1] / 1000,
    )
    curve, rmse = _fit_reserve_curve(service)

    tic = {i.series_id: i for i in service.series_info() if i.series_id.startswith("tic/")}
    tic_latest = max(i.as_of for i in tic.values() if i.as_of is not None)
    holdings: dict[str, float] = {}
    for info in tic.values():
        if info.as_of == tic_latest and info.last_value is not None:
            holdings[info.title.removeprefix("Foreign holdings of Treasuries: ")] = info.last_value

    debt = required_series(service, "fiscal/debt/public") / 1e9
    june_2010 = debt[debt.index <= pd.Timestamp("2010-06-30")]
    if june_2010.empty:
        raise AnchorError("fiscal/debt/public needs history back to June 2010")
    receipts = required_series(service, "fred/MTSR133FMS") / 1000
    outlays = required_series(service, "fred/MTSO133FMS") / 1000
    rows, _ = service.mspd()
    if not rows:
        raise AnchorError("no MSPD securities snapshot")
    ladder, mix = ladder_from_mspd(rows)

    lower, upper = pct("fred/DFEDTARL"), pct("fred/DFEDTARU")
    return USAnchors(
        as_of=as_of,
        corridor=FedCorridor(
            lower=lower, upper=upper, iorb=pct("fred/IORB"), on_rrp=pct("fred/RRPONTSYAWARD")
        ),
        effr=pct("fred/EFFR"),
        par_curve=par,
        zero_curve=zero_curve,
        term_premium=pct("fred/THREEFYTP10"),
        balance_sheet=sheet,
        bank_assets=required_latest(service, "fred/TLAACBW027SBOG")[1],
        observed_qt=QTPlan(
            treasury_cap=_observed_runoff(service, "fred/TREAST"),
            mbs_cap=_observed_runoff(service, "fred/WSHOMCB"),
        ),
        reserve_curve=curve,
        reserve_fit_rmse_bp=rmse,
        dollar_index=required_latest(service, "fred/DTWEXBGS")[1],
        foreign_holdings=holdings,
        tic_as_of=tic_latest,
        debt_public=float(debt.iloc[-1]),
        debt_public_2010=float(june_2010.iloc[-1]),
        nominal_gdp=required_latest(service, "fred/GDP")[1],
        receipts_12m=float(receipts.iloc[-12:].sum()),
        deficit_12m=float(outlays.iloc[-12:].sum() - receipts.iloc[-12:].sum()),
        ladder=ladder,
        issuance_mix=mix,
        mspd_as_of=rows[0].record_date,
        quality={sid: label for sid, label in infos.items() if not sid.startswith("tic/")},
    )
