"""Module A function codes: the Treasury curve, the Fed, QT, debt service and foreign holders."""

import asyncio
from dataclasses import asdict

from app.commands.linkage import shock_fed
from app.commands.parser import (
    CommandError,
    is_days,
    parse_bp,
    parse_days,
    parse_usd_bn,
    resolve_country,
)
from app.commands.registry import CommandResult, command
from app.sim.events import bp, pct, usd_bn
from app.sim.simulator import Simulator
from app.sim.us_market import COUPON_TENORS, DISPLAY_TENORS, USMarket
from sovereign_engine.us.impact import BUCKET_TENORS

PY_SHIFTS_BP = [float(x) for x in range(-300, 325, 25)]
MAX_POLICY_MOVE = 0.02


def _us(sim: Simulator) -> USMarket:
    if sim.us is None:  # registry checks needs_market first; this narrows the type
        raise CommandError(f"Simulator is not running: {sim.error}")
    return sim.us


@command(
    "PY", "PY [tenor]", "Price–yield: duration, convexity, DV01 and the approximation overlay", "US"
)
async def price_yield(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    if len(args) > 1:
        raise CommandError("Usage: PY [tenor], e.g. PY 10Y")
    tenor = args[0] if args else "10Y"
    if tenor not in COUPON_TENORS:
        raise CommandError(f"PY takes a coupon tenor: {', '.join(COUPON_TENORS)}")
    panel = _us(sim).price_yield(tenor, PY_SHIFTS_BP)
    message = (
        f"{tenor} par bond at {pct(panel.ytm)}: modified duration {panel.modified:.2f}, "
        f"convexity {panel.convexity:.1f}, DV01 {panel.dv01:.4f} per 100"
    )
    return CommandResult(True, "PY", message, panel="PY", data=asdict(panel))


@command("UST", "UST", "US Treasury par curve, live, against today's official close", "US")
async def treasury_curve(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    us = _us(sim)
    now, close = us.par_curve(), us.anchors.par_curve
    slope = now["10Y"] - now["2Y"]
    message = (
        f"2Y {pct(now['2Y'])} · 10Y {pct(now['10Y'])} · 30Y {pct(now['30Y'])} · 2s10s {bp(slope)}"
    )
    data = {
        "curve": {k: now[k] for k in DISPLAY_TENORS},
        "official_close": {k: close[k] for k in DISPLAY_TENORS},
        "as_of": us.anchors.as_of.isoformat(),
    }
    return CommandResult(True, "UST", message, panel="UST", data=data)


@command("FED", "FED", "Fed corridor, EFFR, reserves, ON RRP and the QT pace", "US")
async def fed(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    us = _us(sim)
    s = us.state
    c = s.corridor
    message = (
        f"Target range {pct(c.lower)}–{pct(c.upper)}, IORB {pct(c.iorb)}, ON RRP {pct(c.on_rrp)}; "
        f"EFFR {pct(s.effr)} (IORB {bp(s.effr - c.iorb)}); reserves {usd_bn(s.sheet.reserves)} "
        f"({us.reserves_ratio() * 100:.1f}% of bank assets)"
    )
    data = {**us.snapshot(), "reserve_curve": _reserve_curve(us)}
    return CommandResult(True, "FED", message, panel="FED", data=data)


def _reserve_curve(us: USMarket) -> dict[str, float]:
    curve = us.anchors.reserve_curve
    return {
        "abundant": curve.abundant,
        "scarce": curve.scarce,
        "midpoint": curve.midpoint,
        "width": curve.width,
        "fit_rmse_bp": us.anchors.reserve_fit_rmse_bp,
    }


async def _policy(sim: Simulator, args: tuple[str, ...], sign: int, code: str) -> CommandResult:
    if len(args) != 1:
        raise CommandError(f"Usage: {code} 25BP")
    change = sign * abs(parse_bp(args[0]))
    if not 1e-4 <= abs(change) <= MAX_POLICY_MOVE:
        raise CommandError("Policy moves must be between 1 and 200 basis points")
    us = _us(sim)
    before = us.par_curve()
    us.set_policy(change)
    after = us.par_curve()
    c = us.state.corridor
    verb = "hike" if change > 0 else "cut"
    text = (
        f"FOMC {verb} {bp(change)} → target range {pct(c.lower)}–{pct(c.upper)}; "
        f"IORB {pct(c.iorb)}, "
        f"ON RRP {pct(c.on_rrp)}; 2Y {bp(after['2Y'] - before['2Y'])}, "
        f"10Y {bp(after['10Y'] - before['10Y'])}, 30Y {bp(after['30Y'] - before['30Y'])}"
    )
    sim.emit(
        "policy",
        code,
        text,
        {"change": change, "curve_change": {k: after[k] - before[k] for k in after}},
    )
    return CommandResult(True, code, text, panel="FED")


@command(
    "HIKE", "HIKE 25BP", "Raise the fed funds target range (IORB and ON RRP move with it)", "US"
)
async def hike(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    return await _policy(sim, args, +1, "HIKE")


@command("CUT", "CUT 25BP", "Lower the fed funds target range", "US")
async def cut(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    return await _policy(sim, args, -1, "CUT")


@command("QT", "QT 95B | QT OFF", "Set the monthly balance-sheet runoff, or stop it", "US")
async def qt(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    if len(args) != 1:
        raise CommandError("Usage: QT 95B or QT OFF")
    us = _us(sim)
    if args[0] == "OFF":
        us.set_qt(None)
        sim.emit(
            "policy", "QT", "QT stopped: maturing securities are reinvested; reserves stop draining"
        )
        return CommandResult(True, "QT", "QT stopped", panel="FED")
    total = parse_usd_bn(args[0])
    if total <= 0 or total > 500:
        raise CommandError("QT pace must be between $1bn and $500bn a month")
    projection = us.qt_projection(total)
    plan = us.set_qt(total)
    reserves, spread = projection.reserves, projection.effr_iorb_spread
    tp = projection.ten_year_term_premium_change
    start_spread = float(us.anchors.reserve_curve.spread(us.reserves_ratio()))
    text = (
        f"QT {usd_bn(total)}/month ({usd_bn(plan.treasury_cap)} UST + "
        f"{usd_bn(plan.mbs_cap)} MBS) → over 24 months reserves "
        f"{usd_bn(reserves[-1] - us.state.sheet.reserves)} to {usd_bn(reserves[-1])} "
        f"({reserves[-1] / us.anchors.bank_assets * 100:.1f}% of bank assets), EFFR−IORB "
        f"{bp(spread[-1] - start_spread)}, 10Y term premium {bp(tp[-1])}"
    )
    sim.emit("projection", "QT", text, asdict(projection))
    return CommandResult(True, "QT", text, panel="FED", data=asdict(projection))


@command(
    "DEBT", "DEBT", "Federal interest cost: today's curve vs the simulated curve, 10 years", "US"
)
async def debt(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    us = _us(sim)
    result = await asyncio.to_thread(us.debt_service, 120, us.par_curve())
    base, shock = result.baseline_interest, result.shocked_interest
    to_gdp, to_receipts = result.shocked_to_gdp, result.shocked_to_receipts
    message = (
        f"Interest on marketable debt after 1 year: {usd_bn(shock[11])}/yr on the simulated "
        f"curve vs "
        f"{usd_bn(base[11])}/yr on today's ({usd_bn(shock[11] - base[11])}); "
        f"{to_gdp[11] * 100:.2f}% of GDP, {to_receipts[11] * 100:.1f}% of receipts"
    )
    return CommandResult(True, "DEBT", message, panel="DEBT", data=asdict(result))


@command("TIC", "TIC", "Major foreign holders of Treasuries (TIC), live holdings after sales", "US")
async def tic(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    us = _us(sim)
    aggregates = ("Grand Total", "All Other")
    ranked = sorted(
        (
            (k, v)
            for k, v in us.state.holdings.items()
            if k not in aggregates and not k.startswith("Of Which")
        ),
        key=lambda kv: kv[1],
        reverse=True,
    )
    top = ranked[:3]
    message = f"Top holders ({us.anchors.tic_as_of:%b %Y}): " + ", ".join(
        f"{k} {usd_bn(v)}" for k, v in top
    )
    official = us.anchors.foreign_holdings
    selling = {o.country: o for o in us.state.orders}
    # Sales come off the selling country only: the total falls by what every holder has sold.
    sold = sum(official.get(k, v) - v for k, v in ranked)
    official_total = official.get("Grand Total")
    data = {
        "as_of": us.anchors.tic_as_of.isoformat(),
        "holders": [
            {
                "country": k,
                "holdings": v,
                "official": official.get(k, v),
                "selling": k in selling,
            }
            for k, v in ranked
        ],
        "total": None if official_total is None else official_total - sold,
        "official_total": official_total,
    }
    return CommandResult(True, "TIC", message, panel="TIC", data=data)


@command(
    "SHOCK",
    "SHOCK JP 200B [10D] [SHORT|BELLY|LONG] | SHOCK FED 50BP [VRR|OMO|SWAP|HIKE] [VIX+10]",
    "A foreign holder sells Treasuries; or a Fed move runs through to India's money market",
    "US",
)
async def shock(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    if args and args[0] == "FED":
        return await shock_fed(sim, args[1:])
    if len(args) < 2:
        raise CommandError("Usage: SHOCK JP 200B [10D] [SHORT|BELLY|LONG]")
    us = _us(sim)
    country = resolve_country(args[0], us.state.holdings)
    amount = parse_usd_bn(args[1])
    days, mix = 1.0, "BELLY"
    for token in args[2:]:
        if is_days(token):
            days = parse_days(token)
        elif token in BUCKET_TENORS:
            mix = token
        else:
            raise CommandError(
                f"Unexpected {token}: give a pace like 10D and/or SHORT, BELLY or LONG"
            )
    projection = us.project_sale(amount, days, mix)
    us.sell(country, amount, days, mix)
    long_run = projection["long_run"]
    shocked = {k: v + long_run[k] for k, v in us.par_curve().items()}
    debt = await asyncio.to_thread(us.debt_service, 120, shocked)
    delta_1y = debt.delta_by_year["1"]
    end = projection["end_of_sale"]
    dollar = us.params.dollar_pct_per_100bn * amount / 100
    text = (
        f"{country} sells {usd_bn(amount)} of Treasuries ({mix}) over {days:g} days → by the end: "
        f"10Y {bp(end['10Y'])}, 30Y {bp(end['30Y'])}; long run 10Y {bp(long_run['10Y'])} "
        f"→ interest cost "
        f"{usd_bn(delta_1y)}/yr after 1 year; dollar {dollar:+.2f}% (uncalibrated)"
    )
    sim.emit(
        "shock",
        "SHOCK",
        text,
        {"country": country, "amount": amount, "days": days, "mix": mix, **projection},
    )
    data = {**projection, "debt": asdict(debt)}
    return CommandResult(True, "SHOCK", text, panel="UST", data=data)


@command("CORR", "CORR", "Fed funds market next to India's call money market", "X")
async def corridor(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    us = _us(sim)
    c = us.state.corridor
    india = sim.india
    data = {
        "us": {
            "lower": c.lower,
            "upper": c.upper,
            "iorb": c.iorb,
            "on_rrp": c.on_rrp,
            "effr": us.state.effr,
        },
        "india": (
            {"sdf": india.sdf, "repo": india.repo, "msf": india.msf, "wacr": india.wacr()}
            if india
            else None
        ),
    }
    message = f"Fed funds: EFFR {pct(us.state.effr)} in {pct(c.lower)}–{pct(c.upper)}"
    if india:
        message += (
            f". India: WACR {pct(india.wacr())} in {pct(india.sdf)}–{pct(india.msf)} "
            f"(repo {pct(india.repo)})"
        )
    return CommandResult(True, "CORR", message, panel="CORR", data=data)
