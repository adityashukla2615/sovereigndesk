"""System function codes: help, simulation speed, pause/resume, reset and teach mode."""

from app.commands.parser import CommandError, parse_speed
from app.commands.registry import REGISTRY, CommandResult, catalog, command
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
    return CommandResult(True, "HELP", f"{spec.usage}: {spec.summary}{status}", panel="HELP")


@command("SPEED", "SPEED 10X", "Simulation speed as a multiple of 1 sim-minute per second", "SYS")
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


@command("PAUSE", "PAUSE", "Freeze the simulation clock", "SYS")
async def pause(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    sim.paused = True
    return CommandResult(True, "PAUSE", "Simulation paused")


@command("RESUME", "RESUME", "Restart the simulation clock", "SYS")
async def resume(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    sim.paused = False
    return CommandResult(True, "RESUME", "Simulation resumed")


@command("RESET", "RESET", "Clear every shock and policy change; back to the real anchors", "SYS")
async def reset(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    anchors = sim.us.anchors if sim.us else None
    sim.load(anchors)
    return CommandResult(True, "RESET", "Reset to the real anchors; all shocks cleared")


@command(
    "TEACH",
    "TEACH",
    "Toggle teach mode: the economics behind every panel",
    "SYS",
    needs_market=False,
)
async def teach(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    return CommandResult(True, "TEACH", "Teach mode toggled", panel="TEACH")
