"""System function codes: help, simulation speed, pause/resume, reset, teach mode and layouts."""

import re

from app.commands.parser import CommandError, parse_speed
from app.commands.registry import REGISTRY, CommandResult, catalog, command, describe
from app.sim.simulator import DEFAULT_SPEED, Simulator

MAX_SPEED_MULTIPLE = 1440.0
"""1440× the default: one wall-clock second is one simulated day."""


@command("HELP", "HELP [code]", "List functions, or explain one", "SYS", needs_market=False)
async def help_(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    if not args:
        ready = sum(1 for s in REGISTRY.values() if s.available)
        message = (
            f"{ready} functions ready, {len(REGISTRY) - ready} planned. Type HELP <code> for one."
        )
        return CommandResult(True, "HELP", message, panel="HELP", data={"commands": catalog()})
    spec = REGISTRY.get(args[0])
    if spec is None:
        raise CommandError(f"No function {args[0]}. Type HELP for the list.")
    status = "" if spec.available else f" (arrives in {spec.available_in})"
    return CommandResult(
        True,
        "HELP",
        f"{spec.usage}: {spec.summary}{status}",
        panel="HELP",
        data={"commands": catalog(), "command": describe(spec)},
    )


@command(
    "SPEED",
    "SPEED 10X",
    "Simulation speed as a multiple of 1 sim-minute per second",
    "SYS",
    needs_market=False,
)
async def speed(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    if len(args) != 1:
        raise CommandError("Usage: SPEED 10X (1X = one simulated minute per second)")
    multiple = parse_speed(args[0])
    if multiple > MAX_SPEED_MULTIPLE:
        raise CommandError(
            f"Speed is capped at {MAX_SPEED_MULTIPLE:g}X (a simulated day per second)"
        )
    sim.speed = DEFAULT_SPEED * multiple
    return CommandResult(
        True, "SPEED", f"Speed {multiple:g}X: {multiple:g} simulated minutes per second"
    )


@command("PAUSE", "PAUSE", "Freeze the simulation clock", "SYS", needs_market=False)
async def pause(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    sim.paused = True
    return CommandResult(True, "PAUSE", "Simulation paused")


@command("RESUME", "RESUME", "Restart the simulation clock", "SYS", needs_market=False)
async def resume(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    sim.paused = False
    return CommandResult(True, "RESUME", "Simulation resumed")


@command(
    "RESET",
    "RESET",
    "Clear every shock and policy change; back to the real anchors",
    "SYS",
    needs_market=False,
)
async def reset(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    sim.load(sim.us.anchors if sim.us else None, sim.india.anchors if sim.india else None)
    return CommandResult(
        True,
        "RESET",
        f"Reset to the real anchors; all shocks cleared (a new run, seed {sim.seed})",
        data={"refresh": True},
    )


LAYOUT_NAME = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,23}$")
LAYOUT_WORDS = frozenset({"SAVE", "DELETE", "DEFAULT"})
LAYOUT_USAGE = "Usage: LAYOUT, LAYOUT SAVE name, LAYOUT name, LAYOUT DELETE name or LAYOUT DEFAULT"


@command(
    "LAYOUT",
    "LAYOUT [SAVE|DELETE] name | LAYOUT DEFAULT",
    "Save the four panels as a named layout, restore one, or list them (kept in this browser)",
    "SYS",
    needs_market=False,
)
async def layout(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    """Layouts live in the browser: this checks the request and the terminal carries it out."""
    name: str | None = None
    if not args:
        action = "list"
    elif args == ("DEFAULT",):
        action = "default"
    elif len(args) == 2 and args[0] in ("SAVE", "DELETE"):
        action, name = args[0].lower(), args[1]
    elif len(args) == 1:
        action, name = "load", args[0]
    else:
        raise CommandError(LAYOUT_USAGE)
    if name is not None and (name in LAYOUT_WORDS or not LAYOUT_NAME.match(name)):
        raise CommandError("A layout name is up to 24 letters, digits, - or _, e.g. RATES")
    message = {
        "list": "Layouts saved in this browser",
        "default": "Default layout: PY, FED, WACR and UST",
        "save": f"Layout {name}: the four panels saved in this browser",
        "load": f"Layout {name}: restoring its panels",
        "delete": f"Layout {name} deleted from this browser",
    }[action]
    return CommandResult(True, "LAYOUT", message, data={"layout": {"action": action, "name": name}})


@command(
    "TEACH",
    "TEACH",
    "Toggle teach mode: the economics behind every panel",
    "SYS",
    needs_market=False,
)
async def teach(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    return CommandResult(True, "TEACH", "Teach mode toggled", panel="TEACH")
