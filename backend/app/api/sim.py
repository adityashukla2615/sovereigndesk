"""Simulator status and the command catalogue (the terminal's autocomplete reads this)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.commands import catalog
from app.sim.simulator import Simulator

router = APIRouter(tags=["simulator"])


class CommandInfo(BaseModel):
    code: str
    usage: str
    summary: str
    group: str
    available: bool
    available_in: str | None


class SimStatus(BaseModel):
    running: bool
    error: str | None
    paused: bool
    speed: float
    sim_time: str
    anchored_as_of: str | None
    input_quality: list[str]


def get_sim(request: Request) -> Simulator:
    sim: Simulator | None = getattr(request.app.state, "sim", None)
    if sim is None:
        raise HTTPException(status_code=503, detail="simulator is starting")
    return sim


@router.get("/commands", operation_id="getCommands")
def commands() -> list[CommandInfo]:
    return [CommandInfo(**c) for c in catalog()]


@router.get("/sim/status", operation_id="getSimStatus")
def sim_status(sim: Annotated[Simulator, Depends(get_sim)]) -> SimStatus:
    status: dict[str, Any] = sim.status()
    return SimStatus(**status)
