"""In-process topic pub/sub between the simulator and WebSocket connections.

Each subscriber has a bounded queue; a subscriber that falls behind loses its oldest messages
rather than slowing the simulator. (Redis pub/sub for multi-process deployments is opt-in later.)
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

Message = tuple[str, Any]


@dataclass(eq=False)
class Subscription:
    topics: set[str] = field(default_factory=set)
    queue: asyncio.Queue[Message] = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    dropped: int = 0

    def deliver(self, topic: str, data: Any) -> None:
        if topic not in self.topics:
            return
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait((topic, data))


class PubSub:
    def __init__(self) -> None:
        self._subscribers: set[Subscription] = set()

    def subscribe(self) -> Subscription:
        sub = Subscription()
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subscribers.discard(sub)

    def publish(self, topic: str, data: Any) -> None:
        for sub in list(self._subscribers):
            sub.deliver(topic, data)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
