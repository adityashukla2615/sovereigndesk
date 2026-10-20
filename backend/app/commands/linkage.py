"""Cross-market functions: the US → India linkage (LINK, SHOCK FED)."""

import re

from app.commands.parser import CommandError, parse_bp
from app.commands.registry import CommandResult, command
from app.sim.events import flow_bn, inr_cr
from app.sim.linkage import LinkModel, fed_shock, link_panel, preview
from app.sim.simulator import Simulator
from sovereign_engine.linkage import RESPONSES, Response

MAX_FED_MOVE = 0.02
_VIX = re.compile(r"^VIX([+-]?\d+(?:\.\d+)?)$")
SHOCK_USAGE = "SHOCK FED 50BP [NONE|VRR|OMO|SWAP|HIKE] [VIX+10]"


async def _model(sim: Simulator) -> LinkModel:
    model = await sim.link_model()
    if model is None:
        raise CommandError(f"Linkage unavailable: {sim.link_error}")
    return model


def _response(token: str) -> Response | None:
    lowered = token.lower()
    return next((r for r in RESPONSES if r == lowered), None)


def describe(totals: dict[str, float], inr: float, response: str) -> str:
    """The chain in one line, node by node."""
    t = totals
    verb = "sells" if t["rbi_bn"] < 0 else "buys"
    answer = {
        "none": "RBI lets rates move",
        "vrr": f"RBI funds the drain with weekly VRRs (last {inr_cr(t['vrr_cr'])})",
        "omo": f"RBI buys {inr_cr(t['injection_cr'])} of G-secs in weekly OMOs",
        "swap": f"RBI's buy/sell swap injects {inr_cr(t['injection_cr'])}",
        "hike": f"RBI hikes repo {t['repo_bp']:+.0f} bp",
    }[response]
    return (
        f"US 10Y {t['us10y_bp']:+.1f} bp → India 10Y {t['in10y_bp']:+.1f} bp (differential "
        f"{t['differential_bp']:+.1f} bp) → FPI {flow_bn(t['fpi_bn'])} over a month → RBI "
        f"{verb} ${abs(t['rbi_bn']):.2f}bn → rupee {t['inr_pct']:+.2f}% to ₹{inr:.2f} → "
        f"liquidity {inr_cr(t['drain_cr'] + t['injection_cr'])} "
        f"({t['surplus_pct']:+.3f}% of NDTL) → WACR {t['wacr_bp']:+.1f} bp; {answer}"
    )


@command(
    "LINK",
    "LINK [VRR|OMO|SWAP|HIKE]",
    "US → India chain: Fed → US 10Y → FPI flows → rupee → RBI → liquidity → WACR",
    "X",
)
async def link(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    if sim.us is None or sim.india is None:
        raise CommandError("The linkage needs both markets running")
    if len(args) > 1:
        raise CommandError("Usage: LINK, or LINK VRR|OMO|SWAP|HIKE for a preview")
    response: Response = "none"
    if args:
        chosen = _response(args[0])
        if chosen is None:
            raise CommandError(f"Unknown response {args[0]}: one of {', '.join(RESPONSES)}")
        response = chosen
    model = await _model(sim)
    run = sim.link_runs[-1] if sim.link_runs and not args else None
    shown = run.path if run is not None else preview(sim.us, sim.india, model, 0.0025, response)
    data = link_panel(model, sim.india, run, shown, today=sim.sim_day())
    lead = (
        f"US shock of {run.started:%d %b %H:%M} UTC, day {data['progress']['day']} of "
        f"{shown.days}: "
        if run is not None
        else "If the Fed hiked 25 bp now: "
    )
    message = lead + describe(shown.totals(), float(shown.inr[-1]), shown.response)
    return CommandResult(True, "LINK", message, panel="LINK", data=data)


async def shock_fed(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    """SHOCK FED: the Fed moves in the US simulation and the chain runs into India's market."""
    if sim.us is None or sim.india is None:
        raise CommandError("SHOCK FED needs both markets running")
    if not args:
        raise CommandError(f"Usage: {SHOCK_USAGE}")
    change = parse_bp(args[0])
    if not 1e-4 <= abs(change) <= MAX_FED_MOVE:
        raise CommandError("A Fed shock must be between 1 and 200 basis points")
    response: Response = "none"
    vix = 0.0
    for token in args[1:]:
        if (chosen := _response(token)) is not None:
            response = chosen
        elif match := _VIX.match(token):
            vix = float(match[1])
        else:
            raise CommandError(f"Unexpected {token}: {SHOCK_USAGE}")
    model = await _model(sim)
    run = fed_shock(sim.us, sim.india, model, change, response=response, vix=vix, now=sim.sim_time)
    sim.link_runs = [*sim.link_runs[-9:], run]
    t = run.path.totals()
    c = sim.us.state.corridor
    text = (
        f"SHOCK FED {change * 1e4:+.0f} bp (target range {c.lower * 100:.2f}–{c.upper * 100:.2f}%"
        + (f", VIX {vix:+g}" if vix else "")
        + f"), India from {run.days[0]:%a %d %b}: "
        + describe(t, float(run.path.inr[-1]), response)
    )
    details = {"totals": t, "response": response, "us_curve": run.us_curve_bp}
    sim.emit("shock", "LINK", text, details)
    data = link_panel(model, sim.india, run, run.path, today=sim.sim_day())
    return CommandResult(True, "LINK", text, panel="LINK", data=data)
