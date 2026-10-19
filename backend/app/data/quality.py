"""Data-quality tags shown next to every number in the terminal."""

from datetime import date, datetime, timedelta
from enum import StrEnum

LIVE_WINDOW = timedelta(hours=36)
"""A source counts as live if it was fetched successfully this recently (jobs run daily)."""


class Quality(StrEnum):
    LIVE = "LIVE"
    """Fetched from the official source within the live window."""
    CACHED = "CACHED"
    """Fetched live before, but the source has not been refreshed recently (or is failing)."""
    SEED = "SEED"
    """Only available from the committed real-data snapshot."""
    SIMULATED = "SIMULATED"
    """Produced by the simulator from real starting values."""
    SYNTHETIC = "SYNTHETIC"
    """Invented by design (e.g. the synthetic bank universe); never presented as real."""
    MISSING = "MISSING"


def classify(
    stored: str | None,
    last_success: datetime | None,
    now: datetime,
    *,
    source_failing: bool = False,
) -> Quality:
    """Quality of a series from how its newest row was obtained and how healthy its source is."""
    if stored is None:
        return Quality.MISSING
    if stored == Quality.SEED or last_success is None:
        return Quality.SEED
    if source_failing or now - last_success > LIVE_WINDOW:
        return Quality.CACHED
    return Quality.LIVE


def quality_label(
    quality: Quality, *, last_success: datetime | None, seed_date: date | None, now: datetime
) -> str:
    """Short badge text: ``LIVE``, ``CACHED 3d``, ``SEED 2026-10-19``."""
    if quality is Quality.CACHED and last_success is not None:
        age = now - last_success
        return f"CACHED {age.days}d" if age.days else f"CACHED {int(age.total_seconds() // 3600)}h"
    if quality is Quality.SEED and seed_date is not None:
        return f"SEED {seed_date.isoformat()}"
    return quality.value
