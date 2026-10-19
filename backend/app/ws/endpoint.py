"""``/ws``: topic subscriptions in, ``{topic, ts, seq, data}`` envelopes out.

A subscription first receives the topic's current snapshot, then every update the simulator
publishes (``us.tick`` at the tick rate, at most 4 Hz). Commands run through the registry and
answer on the ``command`` topic; their narratives arrive on ``events``.
"""

import asyncio
import contextlib
import itertools
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

import app
from app.commands import CommandResult, execute
from app.sim.pubsub import Subscription
from app.sim.simulator import Simulator
from app.ws.protocol import Command, Envelope, Ping, Subscribe, client_message_adapter

log = logging.getLogger(__name__)
router = APIRouter()


class Connection:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self._seq = itertools.count(1)
        self._lock = asyncio.Lock()

    async def send(self, topic: str, data: Any) -> None:
        # One sender at a time, so sequence numbers reach the client in order.
        async with self._lock:
            envelope = Envelope(topic=topic, ts=datetime.now(UTC), seq=next(self._seq), data=data)
            await self.ws.send_text(envelope.model_dump_json())


async def _pump(conn: Connection, sub: Subscription) -> None:
    while True:
        topic, data = await sub.queue.get()
        await conn.send(topic, data)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    sim: Simulator | None = getattr(ws.app.state, "sim", None)
    conn = Connection(ws)
    sub = sim.bus.subscribe() if sim is not None else None
    pump = asyncio.create_task(_pump(conn, sub)) if sub is not None else None
    await conn.send(
        "status",
        {
            "server": "sovereigndesk",
            "version": app.__version__,
            "sim": sim.status() if sim else None,
        },
    )
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = client_message_adapter.validate_json(raw)
            except ValidationError as exc:
                errors = [
                    {"loc": list(e["loc"]), "msg": e["msg"]}
                    for e in exc.errors(include_url=False, include_input=False)
                ]
                await conn.send("error", {"reason": "invalid message", "errors": errors})
                continue
            match msg:
                case Subscribe(topics=topics):
                    if sub is not None:
                        sub.topics.update(topics)
                    await conn.send("status", {"subscribed": sorted(sub.topics if sub else topics)})
                    for topic in topics:
                        snapshot = sim.snapshot(topic) if sim is not None else None
                        if snapshot is not None:
                            await conn.send(topic, snapshot)
                case Command(text=text):
                    if sim is None:
                        result = CommandResult(False, "", "Simulator is not available")
                    else:
                        result = await execute(sim, text)
                    await conn.send("command", result.to_wire())
                case Ping():
                    await conn.send("pong", {})
    except WebSocketDisconnect:
        log.debug("websocket client disconnected")
    finally:
        if pump is not None:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
        if sim is not None and sub is not None:
            sim.bus.unsubscribe(sub)
