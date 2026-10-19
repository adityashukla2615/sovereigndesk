from datetime import date
from pathlib import Path
from typing import cast

import pytest
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.data.catalog import SeriesSpec
from app.data.scheduler import REFRESH_TIMES, build_scheduler
from app.data.seed import read_manifest, read_series
from app.data.service import DataService
from tests.support import SEED_FETCHED, frame, write_seed

SPEC = SeriesSpec("fred/TEST", "fred", "TEST", "Test", "%", "D")


class _StubService:
    adapters = dict.fromkeys(REFRESH_TIMES)

    def refresh(self, source: str) -> None: ...

    def refresh_stale(self) -> None: ...


def test_scheduler_registers_a_daily_job_per_source_and_a_startup_catch_up() -> None:
    scheduler = build_scheduler(cast(DataService, _StubService()))
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {f"refresh:{s}" for s in REFRESH_TIMES} | {"refresh:startup"}
    trigger = jobs["refresh:treasury"].trigger
    assert isinstance(trigger, CronTrigger)
    assert str(trigger.timezone) == "America/New_York"
    fields = {f.name: str(f) for f in trigger.fields}
    assert (fields["day_of_week"], fields["hour"], fields["minute"]) == ("mon-fri", "18", "30")
    assert not scheduler.running


def test_seed_round_trip_and_tamper_detection(settings: Settings) -> None:
    write_seed(
        settings.seed_dir, [frame(SPEC, [(date(2026, 10, 15), 4.1), (date(2026, 10, 16), 4.2)])]
    )
    manifest = read_manifest(settings.seed_dir)
    assert manifest is not None
    (entry,) = manifest.series
    assert (entry.rows, entry.start, entry.end, entry.fetched_at) == (
        2,
        "2026-10-15",
        "2026-10-16",
        SEED_FETCHED.isoformat(),
    )
    data = read_series(settings.seed_dir, entry)
    assert list(data["value"]) == [4.1, 4.2]
    assert list(data["date"]) == [date(2026, 10, 15), date(2026, 10, 16)]

    path: Path = settings.seed_dir / entry.file
    path.write_text(path.read_text("utf-8").replace("4.2", "9.9"), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        read_series(settings.seed_dir, entry)
