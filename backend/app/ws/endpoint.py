"""Phase 1 WebSocket endpoint: greets with ``status``, echoes commands, acks subscriptions.

The simulator's topics (``us.tick``, ``in.tick``, ...) plug in here from Phase 4.
"""

import itertools
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

import app
from app.ws.protocol import Command, Envelope, Ping, Subscribe, client_message_adapter

log = logging.getLogger(__name__)
router = APIRouter()


class Connection:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self._seq = itertools.count(1)
        self.topics: set[str] = set()

    async def send(self, topic: str, data: Any) -> None:
        envelope = Envelope(topic=topic, ts=datetime.now(UTC), seq=next(self._seq), data=data)
        await self.ws.send_text(envelope.model_dump_json())


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conn = Connection(ws)
    await conn.send("status", {"server": "sovereigndesk", "version": app.__version__})
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
                    conn.topics.update(topics)
                    await conn.send("status", {"subscribed": sorted(conn.topics)})
                case Command(text=text):
                    await conn.send("echo", {"text": text})
                case Ping():
                    await conn.send("pong", {})
    except WebSocketDisconnect:
        log.debug("websocket client disconnected")
