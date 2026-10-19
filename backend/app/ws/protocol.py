"""Wire protocol for ``/ws``. Mirrored by hand in ``frontend/src/ws/protocol.ts``.

Client → server: ``{"op": "subscribe", "topics": [...]}``, ``{"op": "command", "text": "..."}``
or ``{"op": "ping"}``. Server → client: an :class:`Envelope` per message, with ``seq`` strictly
increasing per connection so the client can detect gaps.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _ClientOp(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Subscribe(_ClientOp):
    op: Literal["subscribe"]
    topics: list[str] = Field(min_length=1, max_length=32)


class Command(_ClientOp):
    op: Literal["command"]
    text: str = Field(min_length=1, max_length=256)


class Ping(_ClientOp):
    op: Literal["ping"]


ClientMessage = Annotated[Subscribe | Command | Ping, Field(discriminator="op")]
client_message_adapter: TypeAdapter[Subscribe | Command | Ping] = TypeAdapter(ClientMessage)


class Envelope(BaseModel):
    topic: str
    ts: datetime
    seq: int
    data: Any
