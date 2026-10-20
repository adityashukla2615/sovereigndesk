"""Module B function codes: India's call money market, RBI's corridor and operations, the banks,
and the G-sec curve with its repo pass-through and the spread to US Treasuries."""

from app.commands.parser import (
    CommandError,
    is_days,
    parse_bp,
    parse_days,
    parse_inr_cr,
    parse_percent,
)
from app.commands.registry import CommandResult, command
from app.sim.events import bp, inr_cr, pct
from app.sim.india_market import IST, IndiaMarket, WacrMode
from app.sim.simulator import Simulator
from sovereign_engine.india.auctions import AuctionKind

MAX_REPO_MOVE = 0.02
MAX_AUCTION = 1_000_000.0
"""₹10 lakh crore."""


def _india(sim: Simulator) -> IndiaMarket:
    if sim.india is None:
        raise CommandError(f"India simulator is not running: {sim.india_error}")
    return sim.india


def _corridor_text(m: IndiaMarket) -> str:
    return f"SDF {pct(m.sdf)} · repo {pct(m.repo)} · MSF {pct(m.msf)}"


@command(
    "CALL",
    "CALL",
    "India call money market today: rounds, WACR, high/low, who borrows and lends",
    "IN",
    needs_market=False,
)
async def call(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    m = _india(sim)
    snap = m.snapshot()
    today = snap["call"]
    if today["rounds"]:
        message = (
            f"WACR {pct(m.wacr())} today: {inr_cr(today['volume'])} in {today['rounds']} "
            f"rounds, {pct(today['low'])}–{pct(today['high'])}; {_corridor_text(m)}"
        )
    else:
        message = f"Call market closed; last WACR {pct(m.wacr())}. {_corridor_text(m)}"
    return CommandResult(True, "CALL", message, panel="CALL", data={**snap, **m.call_panel()})


@command(
    "WACR",
    "WACR [POLICY|REALISTIC]",
    "WACR and RBI's corridor: the fitted macro map, real and simulated days; set the mode",
    "IN",
    needs_market=False,
)
async def wacr(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    m = _india(sim)
    a = m.anchors
    if len(args) > 1 or (args and args[0] not in ("POLICY", "REALISTIC")):
        raise CommandError("Usage: WACR, WACR POLICY or WACR REALISTIC")
    if args:
        mode: WacrMode = "policy" if args[0] == "POLICY" else "realistic"
        m.set_mode(mode)
        x = a.excursions
        lower, upper = m.band()
        text = (
            f"Policy mode: call rates stay inside RBI's corridor ({pct(m.sdf)}–{pct(m.msf)})"
            if mode == "policy"
            else "Realistic mode: WACR may leave the corridor as RBI's data shows it does "
            f"({x.below_sdf} days below the SDF and {x.above_msf} above the MSF of "
            f"{x.trading_days} since April 2022), within {pct(lower)}–{pct(upper)}"
        )
        sim.emit("info", "WACR", text, {"mode": mode})
    message = (
        f"WACR {pct(m.wacr())} vs repo {pct(m.repo)} ({bp(m.wacr() - m.repo)}); surplus "
        f"{inr_cr(m.projected_surplus())} = {m.surplus_pct():.2f}% of NDTL puts the map at "
        f"{pct(m.map_rate())} (fit on {a.map_points} days, RMSE {a.map_rmse_bp:.0f} bp)"
    )
    return CommandResult(
        True, "WACR", message, panel="WACR", data={**m.snapshot(), **m.corridor_panel()}
    )


@command(
    "LAF",
    "LAF",
    "RBI's liquidity adjustment facility: SDF, MSF, VRR/VRRR outstanding and auctions",
    "IN",
    needs_market=False,
)
async def laf(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    m = _india(sim)
    panel = m.laf_panel()
    message = (
        f"Last night SDF {inr_cr(panel['sdf'])}, MSF {inr_cr(panel['msf'])}; VRRR "
        f"{inr_cr(m.outstanding('VRRR'))}, VRR {inr_cr(m.outstanding('VRR'))} outstanding; "
        f"net absorption {inr_cr(m.projected_surplus())} ({m.surplus_pct():.2f}% of NDTL)"
    )
    return CommandResult(True, "LAF", message, panel="LAF", data={**m.snapshot(), **panel})


@command(
    "NDTL",
    "NDTL",
    "The SYNTHETIC banks: NDTL, CRR, SLR, MSF capacity, call positions and limits",
    "IN",
    needs_market=False,
)
async def ndtl(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    m = _india(sim)
    rows = m.banks_panel()
    required = sum(r["requirement"] for r in rows)
    message = (
        f"{len(rows)} SYNTHETIC banks scaled to real NDTL {inr_cr(m.ndtl())} (CRR requirement "
        f"÷ CRR); CRR {m.crr * 100:.2f}% → {inr_cr(required)} to hold with RBI"
    )
    return CommandResult(
        True, "NDTL", message, panel="NDTL", data={"banks": rows, "synthetic": True}
    )


@command(
    "CRR",
    "CRR 3.5",
    "Change the cash reserve ratio from the next fortnight and see the liquidity drain",
    "IN",
    needs_market=False,
)
async def crr(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    if len(args) != 1:
        raise CommandError("Usage: CRR 3.5 (per cent of NDTL)")
    m = _india(sim)
    new = parse_percent(args[0])
    old = m.crr
    start, liquidity = m.schedule_crr(new)
    after = (m.projected_surplus() + liquidity) / m.ndtl() * 100
    move = float(
        m.anchors.liquidity_map.spread(after) - m.anchors.liquidity_map.spread(m.surplus_pct())
    )
    verb = "drains" if liquidity < 0 else "releases"
    text = (
        f"CRR {old * 100:.2f}% → {new * 100:.2f}% from the fortnight beginning {start:%d %b %Y}: "
        f"{verb} {inr_cr(abs(liquidity))}; surplus {m.surplus_pct():.2f}% → {after:.2f}% of NDTL, "
        f"map WACR {bp(move)}"
    )
    sim.emit("policy", "CRR", text, {"crr": new, "from": start.isoformat(), "liquidity": liquidity})
    return CommandResult(True, "CRR", text, panel="LAF")


@command(
    "REPO",
    "REPO +25BP",
    "Change the policy repo rate; the SDF and MSF move with it at once",
    "IN",
    needs_market=False,
)
async def repo(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    if len(args) != 1:
        raise CommandError("Usage: REPO +25BP or REPO -25BP")
    change = parse_bp(args[0])
    if not 1e-4 <= abs(change) <= MAX_REPO_MOVE:
        raise CommandError("Repo moves must be between 1 and 200 basis points")
    m = _india(sim)
    old = m.repo
    m.set_repo(change)
    text = (
        f"MPC {'hike' if change > 0 else 'cut'} {bp(change)}: repo {pct(old)} → {pct(m.repo)}; "
        f"{_corridor_text(m)}; the call market re-centres at {pct(m.map_rate())}"
    )
    if m.gsec is not None:
        moves = ", ".join(f"{t} {bp(m.gsec.betas[t] * change)}" for t in ("2Y", "10Y", "30Y"))
        text += f"; G-secs {moves} (event-study pass-through)"
    sim.emit("policy", "REPO", text, {"change": change, "repo": m.repo})
    return CommandResult(True, "REPO", text, panel="WACR")


async def _operation(sim: Simulator, args: tuple[str, ...], kind: AuctionKind) -> CommandResult:
    if not 1 <= len(args) <= 2:
        raise CommandError(f"Usage: {kind} 50000CR [7D]")
    amount = parse_inr_cr(args[0])
    if amount > MAX_AUCTION:
        raise CommandError("Auctions are capped at ₹10 lakh crore")
    tenor = 1
    if len(args) == 2:
        if not is_days(args[1]):
            raise CommandError(f"Expected a tenor like 7D, got {args[1]}")
        tenor = round(parse_days(args[1]))
    m = _india(sim)
    when = m.order_auction(kind, amount, tenor)
    verb = "inject" if kind == "VRR" else "absorb"
    text = (
        f"{kind} of {inr_cr(amount)} for {tenor} day(s) to {verb} liquidity: bids taken at "
        f"{when.astimezone(IST):%a %d %b %H:%M} IST"
    )
    return CommandResult(True, kind, text, panel="LAF", data={"runs_at": when.isoformat()})


@command(
    "VRR",
    "VRR 50000CR [7D]",
    "Variable rate repo auction: RBI lends (injection)",
    "IN",
    needs_market=False,
)
async def vrr(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    return await _operation(sim, args, "VRR")


@command(
    "VRRR",
    "VRRR 50000CR [7D]",
    "Variable rate reverse repo auction: RBI borrows (absorption)",
    "IN",
    needs_market=False,
)
async def vrrr(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    return await _operation(sim, args, "VRRR")


@command(
    "TAXCAL",
    "TAXCAL",
    "Advance-tax and GST liquidity calendar: real WACR − repo by day and the tax days ahead",
    "IN",
    needs_market=False,
)
async def taxcal(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    m = _india(sim)
    data = m.heatmap()
    tax = m.anchors.tax
    nxt = data["tax_days"][0]["date"] if data["tax_days"] else None
    message = (
        f"Advance tax drains a median {inr_cr(tax.advance_tax_drain)} around the 15th of "
        f"Mar/Jun/Sep/Dec and GST {inr_cr(tax.gst_drain)} around the 20th (RBI data, "
        f"{tax.events} episodes); next tax day {nxt}"
    )
    return CommandResult(True, "TAXCAL", message, panel="TAXCAL", data=data)


@command(
    "GSEC",
    "GSEC",
    "India G-sec curve (NSS) and how a repo change passes through it, by maturity",
    "IN",
    needs_market=False,
)
async def gsec(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    m = _india(sim)
    panel = m.gsec_panel()
    if m.gsec is None or panel is None:
        raise CommandError(f"G-sec curve unavailable: {m.anchors.gsec_error}")
    g = m.gsec
    points, fit = g.points, g.anchors.passthrough
    message = (
        f"G-secs: 91D {pct(points['3M'])}, 2Y {pct(points['2Y'])}, 10Y {pct(points['10Y'])}, "
        f"30Y {pct(points['30Y'])} (NSS within {g.fit.rmse_bp:.1f} bp); a repo surprise moves "
        f"2Y by {g.betas['2Y']:.2f} and 10Y by {g.betas['10Y']:.2f} of itself "
        f"(event study on {len(g.anchors.events)} repo changes, 10Y band "
        f"{fit.beta_10y_band[0]:.2f}–{fit.beta_10y_band[1]:.2f})"
    )
    return CommandResult(True, "GSEC", message, panel="GSEC", data=panel)


@command(
    "SPRD",
    "SPRD",
    "India 10Y against US 10Y: the spread, real history and simulated days",
    "X",
    needs_market=False,
)
async def sprd(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    m = _india(sim)
    panel = sim.spread_panel()
    if panel is None:
        raise CommandError(f"G-sec curve unavailable: {m.anchors.gsec_error}")
    now = panel["now"]
    if now["spread"] is None:
        message = f"India 10Y {pct(now['india'])}; the US market is not running: {sim.error}"
    else:
        real = panel["real"]
        since = (
            f"; {bp(real[-1]['india'] - real[-1]['us'])} on {real[-1]['date']}, "
            f"{bp(real[0]['india'] - real[0]['us'])} on {real[0]['date']}"
            if real
            else ""
        )
        message = (
            f"India 10Y {pct(now['india'])} − US 10Y {pct(now['us'])} = {bp(now['spread'])}{since}"
        )
    return CommandResult(True, "SPRD", message, panel="SPRD", data=panel)
