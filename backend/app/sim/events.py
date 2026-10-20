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
        self.total = 0
        """Events ever added (the deque forgets old ones; this keeps counting)."""

    def add(self, event: Event) -> Event:
        self._events.append(event)
        self.total += 1
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
    """USD billions with a sensible unit: 50 → '$50bn', 1234 → '$1.23tn', -2280 → '−$2.28tn'."""
    sign, size = ("−" if amount < 0 else ""), abs(amount)
    if size >= 1000:
        return f"{sign}${size / 1000:,.2f}tn"
    return f"{sign}${size:,.0f}bn" if size >= 10 else f"{sign}${size:,.1f}bn"


def inr(amount: float) -> str:
    """Rupees in the Indian grouping: 1900000 → '₹19,00,000', -34000.4 → '−₹34,000'."""
    sign, digits = ("−" if amount < 0 else ""), f"{abs(amount):.0f}"
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        head, group = head[:-2], head[-2:]
        groups.insert(0, group)
    grouped = ",".join([g for g in (head, *groups) if g] + [tail])
    return f"{sign}₹{grouped}"


def flow_bn(amount: float) -> str:
    """A signed flow in USD billions, to the ten million: -0.5 → '−$0.50bn', 3.2 → '+$3.20bn'."""
    sign = "−" if amount < 0 else "+"
    return f"{sign}${abs(amount):,.2f}bn"


def pct(rate: float, digits: int = 2) -> str:
    return f"{rate * 100:.{digits}f}%"


def inr_cr(amount: float) -> str:
    """Rupees in crore, switching to lakh crore at ₹1 lakh crore: 34528 → '₹34,528 cr'."""
    sign, size = ("−" if amount < 0 else ""), abs(amount)
    if size >= 100_000:
        return f"{sign}₹{size / 100_000:,.2f} lakh cr"
    return f"{sign}₹{size:,.0f} cr"
