"""Module D: REPLAY, real episodes replayed against the model."""

import asyncio
from pathlib import Path

from app.commands.parser import CommandError
from app.commands.registry import CommandResult, command
from app.config import REPO_ROOT
from app.sim.replay import (
    ReplayResult,
    episode_ids,
    load_episode,
    replay_panel,
    run_advtax,
    run_dash,
    run_gilt,
    run_hike,
    run_taper,
)
from app.sim.simulator import Simulator

USAGE = "REPLAY TAPER2013 | DASH2020 | GILT2022 | HIKE2022 | ADVTAX"


def replay_root(sim: Simulator) -> Path:
    data = sim.data
    return data.settings.replay_dir if data is not None else REPO_ROOT / "data" / "replays"


async def _run(sim: Simulator, root: Path, episode_id: str) -> ReplayResult:
    ep = load_episode(root, episode_id)
    if ep.model == "taper":
        link = await sim.link_model()
        if link is None:
            raise CommandError(f"The taper replay needs the linkage: {sim.link_error}")
        return await asyncio.to_thread(run_taper, ep, link.params)
    if ep.model == "gilt":
        return await asyncio.to_thread(run_gilt, ep)
    if ep.model == "dash":
        gilt = load_episode(root, "GILT2022")
        impact = sim.us.impact if sim.us is not None else None
        return await asyncio.to_thread(run_dash, ep, gilt, impact)
    if sim.india is None:
        raise CommandError("This replay needs the India market's liquidity map")
    liquidity_map = sim.india.anchors.liquidity_map
    if ep.model == "hike":
        passthrough = sim.us.params.policy_passthrough if sim.us is not None else 0.5
        return await asyncio.to_thread(run_hike, ep, liquidity_map, passthrough=passthrough)
    if ep.model == "advtax":
        return await asyncio.to_thread(run_advtax, ep, liquidity_map)
    raise CommandError(f"no runner for {ep.model}")


@command(
    "REPLAY",
    USAGE,
    "Replay a real episode: the model driven by what moved, against what happened",
    "X",
    needs_market=False,
)
async def replay(sim: Simulator, args: tuple[str, ...]) -> CommandResult:
    root = replay_root(sim)
    ids = episode_ids(root)
    if not ids:
        raise CommandError(f"No replay datasets in {root}: run py tasks.py replays")
    if not args:
        return CommandResult(True, "REPLAY", "Replays: " + ", ".join(ids) + f". Usage: {USAGE}")
    episode_id = args[0].upper()
    if episode_id not in ids:
        raise CommandError(f"Unknown replay {args[0]}: one of {', '.join(ids)}")
    try:
        result = await _run(sim, root, episode_id)
    except CommandError:
        raise
    except Exception as exc:  # a dataset that does not fit its runner
        raise CommandError(f"Replay {episode_id} failed: {type(exc).__name__}: {exc}") from exc
    available = [{"id": i, "title": load_episode(root, i).title} for i in ids]
    panel = replay_panel(result, available)
    first = result.targets[0]
    message = f"{result.episode.title}: " + "; ".join(first.summary[:2])
    return CommandResult(True, "REPLAY", message, panel="REPLAY", data=panel)
