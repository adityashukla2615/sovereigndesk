"""The command registry: every function code, its usage and handler, in one place.

The frontend's autocomplete and HELP both read this registry, so it lists functions that later
phases will implement too, flagged as not yet available.
"""

import difflib
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from app.commands.parser import CommandError, tokenize
from app.sim.simulator import Simulator

Group = Literal["US", "IN", "X", "SYS"]


@dataclass(frozen=True, slots=True)
class CommandResult:
    ok: bool
    code: str
    message: str
    panel: str | None = None
    """Function whose panel the terminal should show (e.g. ``PY``)."""
    data: dict[str, Any] | None = None
    narrated: bool = False
    """The handler also put this story in the event log, so the log need not repeat the reply."""
    sim_time: str | None = None
    command: str | None = None
    """The command as run (``PY 10Y``), so the terminal can run it again, e.g. for a layout."""

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


Handler = Callable[[Simulator, tuple[str, ...]], Awaitable[CommandResult]]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    code: str
    usage: str
    summary: str
    group: Group
    handler: Handler | None
    needs_market: bool = True
    available_in: str | None = None
    """For planned functions: the phase that delivers them."""

    @property
    def available(self) -> bool:
        return self.handler is not None


REGISTRY: dict[str, CommandSpec] = {}


def command(
    code: str, usage: str, summary: str, group: Group, *, needs_market: bool = True
) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        REGISTRY[code] = CommandSpec(code, usage, summary, group, handler, needs_market)
        return handler

    return register


def planned(code: str, usage: str, summary: str, group: Group, phase: str) -> None:
    REGISTRY[code] = CommandSpec(code, usage, summary, group, None, available_in=phase)


def describe(s: CommandSpec) -> dict[str, Any]:
    return {
        "code": s.code,
        "usage": s.usage,
        "summary": s.summary,
        "group": s.group,
        "available": s.available,
        "available_in": s.available_in,
    }


def catalog() -> list[dict[str, Any]]:
    return [describe(s) for s in sorted(REGISTRY.values(), key=lambda s: (s.group, s.code))]


async def execute(sim: Simulator, text: str) -> CommandResult:
    try:
        parsed = tokenize(text)
    except CommandError as exc:
        return CommandResult(False, "", str(exc))
    spec = REGISTRY.get(parsed.code)
    if spec is None:
        close = difflib.get_close_matches(parsed.code, list(REGISTRY), n=1)
        hint = f" Did you mean {close[0]}?" if close else ""
        return CommandResult(
            False, parsed.code, f"Unknown function {parsed.code}.{hint} Type HELP."
        )
    if spec.handler is None:
        return CommandResult(False, spec.code, f"{spec.code} arrives in {spec.available_in}.")
    if spec.needs_market and sim.us is None:
        return CommandResult(False, spec.code, f"Simulator is not running: {sim.error}")
    before = sim.events.total
    try:
        result = await spec.handler(sim, parsed.args)
    except (CommandError, ValueError) as exc:
        result = CommandResult(False, spec.code, str(exc))
    return replace(
        result,
        narrated=sim.events.total > before,
        sim_time=sim.sim_time.isoformat(),
        command=" ".join((parsed.code, *parsed.args)),
    )
