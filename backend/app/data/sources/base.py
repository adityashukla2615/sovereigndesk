"""What every source adapter returns, and the errors it may raise."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

import pandas as pd

from app.data.catalog import SeriesSpec
from app.data.errors import SourceError

__all__ = ["Adapter", "FetchOutcome", "Provenance", "SeriesFrame", "SourceError", "tidy"]


@dataclass(frozen=True, slots=True)
class Provenance:
    source: str
    url: str
    """Request URL with secrets removed."""
    fetched_at: datetime
    from_cache: bool = False
    """True when the live request failed and the last good raw response was re-parsed."""


@dataclass(frozen=True, slots=True)
class SeriesFrame:
    """One series as a tidy frame with columns ``date`` (datetime.date) and ``value`` (float)."""

    spec: SeriesSpec
    data: pd.DataFrame
    provenance: Provenance

    def __post_init__(self) -> None:
        if list(self.data.columns) != ["date", "value"]:
            raise ValueError("series frames must have exactly the columns date, value")


@dataclass(slots=True)
class FetchOutcome:
    frames: list[SeriesFrame] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    """Per-series (or per-request) failures that did not abort the whole fetch."""


class Adapter(Protocol):
    source: str

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome: ...


def tidy(points: list[tuple[date, float]]) -> pd.DataFrame:
    """Sorted, de-duplicated (last value wins) frame of (date, value) points."""
    frame = pd.DataFrame(points, columns=["date", "value"])
    frame = frame.drop_duplicates(subset="date", keep="last").sort_values("date")
    return frame.reset_index(drop=True)
