"""Scenarios and exports: SAVE and LOAD a run, EXPORT the focused panel."""

import asyncio
import re

from sqlalchemy.orm import Session, sessionmaker

from app.commands.parser import CommandError
from app.commands.registry import CommandResult, command, execute
from app.sim.scenarios import Scenario, capture, get, save, saved
from app.sim.simulator import Simulator

NAME = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,23}$")


def _sessions(sim: Simulator) -> sessionmaker[Session]:
    if sim.data is None:
        raise CommandError("Scenarios are kept in the database, and there is none here")
    return sim.data.sessions


def _name(token: str) -> str:
    if not NAME.match(token):
        raise CommandError("A scenario name is up to 24 letters, digits, - or _, e.g. TAPER")
    return token


def _when(s: Scenario) -> str:
    return f"{s.started:%a %d %b %H:%M} → {s.saved_at:%a %d %b %H:%M} UTC"


@command(
    "SAVE",
    "SAVE name",
    "Save this run as a scenario: its seed, start and every command that changed the markets",
    "SYS",
    needs_market=False,
)
async def save_(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    if len(args) != 1:
        raise CommandError("Usage: SAVE name, e.g. SAVE TAPER")
    if sim.us is None and sim.india is None:
        raise CommandError("Nothing to save: neither market is running")
    scenario = capture(sim, _name(args[0]))
    replaced = await asyncio.to_thread(save, _sessions(sim), scenario)
    texts = [text for _, text in scenario.commands]
    steps = ", ".join(texts[:5]) + (", …" if len(texts) > 5 else "") or "no commands yet"
    message = (
        f"Scenario {scenario.name} {'replaced' if replaced else 'saved'}: seed {scenario.seed}, "
        f"{_when(scenario)}, {len(scenario.commands)} command(s) ({steps}). LOAD "
        f"{scenario.name} replays it exactly"
    )
    return CommandResult(True, "SAVE", message)


@command(
    "LOAD",
    "LOAD [name]",
    "Replay a saved scenario from its start to where it was saved; LOAD alone lists them",
    "SYS",
    needs_market=False,
)
async def load(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    sessions = _sessions(sim)
    if not args:
        scenarios = await asyncio.to_thread(saved, sessions)
        if not scenarios:
            return CommandResult(True, "LOAD", "No scenarios saved yet: SAVE name keeps this run")
        listing = "; ".join(f"{s.name} ({len(s.commands)} commands, {_when(s)})" for s in scenarios)
        return CommandResult(True, "LOAD", f"Saved scenarios: {listing}")
    if len(args) != 1:
        raise CommandError("Usage: LOAD name, or LOAD to list the saved scenarios")
    scenario = await asyncio.to_thread(get, sessions, _name(args[0]))
    if scenario is None:
        raise CommandError(f"No scenario {args[0]}. Type LOAD to list them")
    us = sim.us.anchors if sim.us is not None else None
    india = sim.india.anchors if sim.india is not None else None
    notes = []
    if us is not None and scenario.us_as_of not in (None, us.as_of):
        notes.append(f"US data now runs to {us.as_of} (saved on {scenario.us_as_of})")
    if india is not None and scenario.india_as_of not in (None, india.as_of):
        notes.append(f"India's to {india.as_of} (saved on {scenario.india_as_of})")
    sim.loading = scenario.name
    failed: list[str] = []
    try:
        sim.load(us, india, seed=scenario.seed, start=scenario.started)
        for at, text in scenario.commands:
            await asyncio.to_thread(sim.fast_forward, at)
            result = await execute(sim, text, replaying=True)
            if not result.ok:
                failed.append(f"{text}: {result.message}")
        await asyncio.to_thread(sim.fast_forward, scenario.saved_at)
    finally:
        sim.loading = None
    message = (
        f"Scenario {scenario.name} loaded: seed {scenario.seed}, {len(scenario.commands)} "
        f"command(s) replayed, {_when(scenario)}"
    )
    if notes:
        message += "; the path may differ, since " + " and ".join(notes)
    if failed:
        message += "; did not run again: " + "; ".join(failed)
    sim.emit("info", "LOAD", message)
    return CommandResult(True, "LOAD", message, data={"refresh": True})


@command(
    "EXPORT",
    "EXPORT CSV|PNG",
    "Export the focused panel: its data as CSV, or its charts as one PNG",
    "SYS",
    needs_market=False,
)
async def export(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    """The browser does the exporting: this checks the request."""
    if len(args) != 1 or args[0] not in ("CSV", "PNG"):
        raise CommandError("Usage: EXPORT CSV (the panel's data) or EXPORT PNG (its charts)")
    fmt = args[0].lower()
    return CommandResult(
        True,
        "EXPORT",
        f"Exporting the focused panel as {args[0]}",
        data={"export": {"format": fmt}},
    )
