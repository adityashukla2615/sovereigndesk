"""The event log: every shock and policy action explained in plain language with its numbers."""

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

EventKind = Literal["policy", "shock", "projection", "info", "warning"]


@dataclass(frozen=True, slots=True)
class Event:
    sim_time: datetime
    kind: EventKind
    code: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        wire = asdict(self)
        wire["sim_time"] = self.sim_time.isoformat()
        return wire


class EventLog:
    def __init__(self, limit: int = 500) -> None:
        self._events: deque[Event] = deque(maxlen=limit)

    def add(self, event: Event) -> Event:
        self._events.append(event)
        return event

    def recent(self, n: int = 100) -> list[Event]:
        return list(self._events)[-n:]

    def clear(self) -> None:
        self._events.clear()


def bp(change: float) -> str:
    """Signed basis points: 0.0018 → '+18 bp'."""
    value = change * 1e4
    return f"{value:+.0f} bp" if abs(value) >= 0.5 else f"{value:+.1f} bp"


def usd_bn(amount: float) -> str:
    """USD billions with a sensible unit: 50 → '$50bn', 1234 → '$1.23tn'."""
    if abs(amount) >= 1000:
        return f"${amount / 1000:,.2f}tn"
    return f"${amount:,.0f}bn" if abs(amount) >= 10 else f"${amount:,.1f}bn"


def pct(rate: float, digits: int = 2) -> str:
    return f"{rate * 100:.{digits}f}%"
