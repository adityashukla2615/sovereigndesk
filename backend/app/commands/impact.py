"""Module E: IMPACT, what the simulated shocks mean for an investor and a small business."""

import re
from typing import Any

from app.commands.parser import CommandError, parse_bp
from app.commands.registry import CommandResult, command
from app.sim.events import inr
from app.sim.impact import PROFILES, ImpactModel, Shock, impact_panel, read_shock
from app.sim.simulator import Simulator

USAGE = "IMPACT [RETAIL | BUSINESS [SHOP|IMPORTER]] [+100BP] [INR+5]"
_INR = re.compile(r"^INR([+-]?\d+(?:\.\d+)?)%?$")


async def impact_model(sim: Simulator) -> ImpactModel:
    model = await sim.impact_model()
    if model is None:
        raise CommandError(f"Impact unavailable: {sim.impact_error}")
    return model


def shock_for(
    sim: Simulator, *, shift_bp: float | None, repo_bp: float | None, inr_pct: float | None
) -> Shock:
    """The simulation's shock, or a hypothetical one; the rupee's base is FBIL's reference
    rate the linkage anchored to, once it has run."""
    if sim.india is None:
        raise CommandError("IMPACT needs the India market running")
    inr_base = sim.link.inr if sim.link is not None else None
    try:
        return read_shock(
            sim.india, inr_base=inr_base, shift_bp=shift_bp, repo_bp=repo_bp, inr_pct=inr_pct
        )
    except Exception as exc:
        raise CommandError(f"Impact unavailable: {exc}") from exc


def describe(panel: dict[str, Any], view: str, profile: str | None) -> str:
    s = panel["shock"]
    lead = (
        "Simulated moves since the anchors" if s["source"] == "simulation" else "Hypothetical move"
    )
    head = f"{lead}: repo {s['repo_bp']:+.0f} bp, 10Y G-sec "
    ten = next((c for c in s["curve"] if c["tenor"] == "10Y"), None)
    head += f"{ten['change_bp']:+.1f} bp" if ten else "—"
    head += f", rupee {s['inr_pct']:+.2f}%" if s["inr_pct"] else ""
    if view == "RETAIL":
        t = panel["retail"]["totals"]
        return (
            f"{head}. Portfolio (ILLUSTRATIVE): {inr(t['value0'])} → {inr(t['value1'])} "
            f"({t['change_pct']:+.2f}%), modified duration {t['modified_duration']:.2f}, "
            f"DV01 {inr(t['dv01'])} per bp"
        )
    rows = panel["business"]
    chosen = [r for r in rows if profile is None or r["key"] == profile]
    parts = [
        f"{r['name']}: loan {r['summary']['loan_rate_bp']:+.0f} bp, interest "
        f"{inr(r['summary']['interest'])}/month, margin {inr(r['summary']['margin'])}/month "
        f"({r['summary']['margin_pct']:+.1f}%) after {len(r['months'])} months"
        for r in chosen
    ]
    return f"{head}. " + "; ".join(parts) + " (ILLUSTRATIVE profiles)"


@command("IMPACT", USAGE, "What a shock means for a bond portfolio and for a small business", "X")
async def impact(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    view, profile = "RETAIL", None
    shift_bp: float | None = None
    inr_pct: float | None = None
    rest = list(args)
    if rest and rest[0] in ("RETAIL", "BUSINESS"):
        view = rest.pop(0)
        if view == "BUSINESS" and rest and rest[0] in PROFILES:
            profile = rest.pop(0)
    for token in rest:
        if match := _INR.match(token):
            inr_pct = float(match[1])
        else:
            try:
                shift_bp = parse_bp(token) * 1e4
            except CommandError:
                raise CommandError(f"Unexpected {token}: {USAGE}") from None
    model = await impact_model(sim)
    # +100BP: a parallel yield shift for the portfolio, a repo move for the businesses.
    if view == "RETAIL":
        shock = shock_for(sim, shift_bp=shift_bp, repo_bp=None, inr_pct=inr_pct)
    else:
        shock = shock_for(sim, shift_bp=None, repo_bp=shift_bp, inr_pct=inr_pct)
    if sim.india is None:  # checked by shock_for; narrows the type
        raise CommandError("IMPACT needs the India market running")
    panel = impact_panel(model, sim.india, shock)
    panel["view"] = view
    panel["profile"] = profile
    return CommandResult(True, "IMPACT", describe(panel, view, profile), panel="IMPACT", data=panel)
