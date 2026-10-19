"""Data service: seed bootstrap, refresh outcomes and the quality tags they produce."""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine

from app.config import Settings
from app.data.catalog import SeriesSpec
from app.data.quality import Quality
from app.data.service import REFRESH_LOOKBACK, DataService
from app.data.sources.base import FetchOutcome, SeriesFrame, SourceError
from app.db.session import make_engine, make_session_factory, upgrade_database
from tests.support import frame, write_seed

SPEC = SeriesSpec("fred/TEST", "fred", "TEST", "Test series", "%", "D")
NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)


class FakeAdapter:
    source = "fred"

    def __init__(self) -> None:
        self.calls = 0
        self.starts: list[date | None] = []
        self.frames: list[SeriesFrame] = []
        self.errors: dict[str, str] = {}
        self.fail: str | None = None

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        self.calls += 1
        self.starts.append(start)
        if self.fail:
            raise SourceError(self.fail)
        return FetchOutcome(list(self.frames), dict(self.errors))


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def online(settings: Settings) -> Settings:
    return settings.model_copy(update={"offline": False})


ServiceFactory = Callable[[Settings, FakeAdapter, Clock], DataService]


@pytest.fixture
def make_service() -> Iterator[ServiceFactory]:
    engines: list[Engine] = []

    def build(settings: Settings, adapter: FakeAdapter, clock: Clock) -> DataService:
        engine = make_engine(settings.database_url)
        engines.append(engine)
        upgrade_database(engine)
        sessions = make_session_factory(engine)
        service = DataService(settings, sessions, {"fred": adapter}, clock=clock)
        service.bootstrap()
        return service

    yield build
    for engine in engines:
        engine.dispose()


def _info(service: DataService) -> tuple[Quality, str]:
    (info,) = service.series_info({SPEC.series_id})
    return info.quality, info.label


def test_bootstrap_loads_seed_once(online: Settings, make_service: ServiceFactory) -> None:
    write_seed(
        online.seed_dir, [frame(SPEC, [(date(2026, 10, 15), 4.1), (date(2026, 10, 16), 4.2)])]
    )
    service = make_service(online, FakeAdapter(), Clock(NOW))
    assert _info(service) == (Quality.SEED, "SEED 2026-10-19")
    assert service.bootstrap() == 0  # already present: not reloaded
    view = service.series(SPEC.series_id)
    assert view is not None
    assert view.values == [4.1, 4.2]


def test_live_refresh_then_ageing_to_cached(online: Settings, make_service: ServiceFactory) -> None:
    write_seed(online.seed_dir, [frame(SPEC, [(date(2026, 10, 15), 4.1)])])
    adapter, clock = FakeAdapter(), Clock(NOW)
    adapter.frames = [
        frame(SPEC, [(date(2026, 10, 15), 4.15), (date(2026, 10, 19), 4.3)], when=NOW)
    ]
    service = make_service(online, adapter, clock)

    report = service.refresh("fred")
    assert (report.status, report.rows) == ("ok", 2)
    assert _info(service) == (Quality.LIVE, "LIVE")
    assert service.latest_values([SPEC.series_id]) == {SPEC.series_id: (date(2026, 10, 19), 4.3)}
    view = service.series(SPEC.series_id, start=date(2026, 10, 16))
    assert view is not None
    assert view.values == [4.3]  # the live row replaced the seed row for 15 Oct

    clock.now = NOW + timedelta(days=2, hours=1)
    assert _info(service) == (Quality.CACHED, "CACHED 2d")


def test_failed_refresh_keeps_data_and_flags_cached(
    online: Settings, make_service: ServiceFactory
) -> None:
    adapter, clock = FakeAdapter(), Clock(NOW)
    adapter.frames = [frame(SPEC, [(date(2026, 10, 19), 4.3)], when=NOW)]
    service = make_service(online, adapter, clock)
    service.refresh("fred")

    clock.now = NOW + timedelta(hours=3)
    adapter.fail = "fred: ConnectError: cannot reach https://x.test/?api_key=" + "fake" * 8
    report = service.refresh("fred")
    assert report.status == "error"
    (source,) = service.sources()
    assert source.status == "error"
    assert source.last_success_at == NOW  # the earlier success is remembered
    assert "fake" * 8 not in source.message  # redacted
    assert _info(service) == (Quality.CACHED, "CACHED 3h")
    view = service.series(SPEC.series_id)
    assert view is not None
    assert view.values == [4.3]


def test_simulated_outage_and_offline_mode(online: Settings, make_service: ServiceFactory) -> None:
    adapter = FakeAdapter()
    outage = make_service(online.model_copy(update={"fail_sources": ["fred"]}), adapter, Clock(NOW))
    assert outage.refresh("fred").status == "error"
    assert adapter.calls == 0

    offline = make_service(online.model_copy(update={"offline": True}), adapter, Clock(NOW))
    assert offline.refresh("fred").status == "skipped"
    assert offline.refresh_stale()[0].status == "skipped"
    assert adapter.calls == 0


def test_partial_and_cached_outcomes(online: Settings, make_service: ServiceFactory) -> None:
    adapter, clock = FakeAdapter(), Clock(NOW)
    service = make_service(online, adapter, clock)
    adapter.frames = [frame(SPEC, [(date(2026, 10, 19), 4.3)], when=NOW)]
    adapter.errors = {"fred/OTHER": "HTTP 500"}
    assert service.refresh("fred").status == "partial"
    assert _info(service)[0] is Quality.LIVE  # what did arrive is live

    adapter.errors = {}
    adapter.frames = [frame(SPEC, [(date(2026, 10, 19), 4.3)], when=NOW, from_cache=True)]
    clock.now = NOW + timedelta(hours=1)
    assert service.refresh("fred").status == "cached"
    assert _info(service)[0] is Quality.CACHED


def test_refresh_stale_skips_fresh_sources(online: Settings, make_service: ServiceFactory) -> None:
    adapter, clock = FakeAdapter(), Clock(NOW)
    adapter.frames = [frame(SPEC, [(date(2026, 10, 19), 4.3)], when=NOW)]
    service = make_service(online, adapter, clock)
    assert len(service.refresh_stale()) == 1
    clock.now = NOW + timedelta(hours=12)
    assert service.refresh_stale() == []
    clock.now = NOW + timedelta(hours=40)
    assert len(service.refresh_stale()) == 1


def test_unknown_series_and_empty_seed(online: Settings, make_service: ServiceFactory) -> None:
    service = make_service(online, FakeAdapter(), Clock(NOW))
    assert service.series("fred/NOPE") is None
    assert service.mspd() == ([], Quality.MISSING)
    statics = {i.series_id: i for i in service.series_info()}
    assert statics["fred/DGS10"].quality is Quality.MISSING  # catalogued, never loaded


def test_refresh_windows_are_per_source(online: Settings, make_service: ServiceFactory) -> None:
    adapter = FakeAdapter()
    service = make_service(online, adapter, Clock(NOW))
    service.adapters.update(rbi=adapter, fbil=adapter)
    for source in ("fred", "rbi", "fbil"):
        service.refresh(source)
    today = NOW.date()
    # RBI pages its archive by month: a daily refresh must not crawl two years of it.
    assert adapter.starts == [
        today - REFRESH_LOOKBACK,
        today - timedelta(days=7),
        today - timedelta(days=30),
    ]
