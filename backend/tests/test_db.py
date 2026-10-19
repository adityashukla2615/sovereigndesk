from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, func, inspect, select

from app.db.models import Base, Observation
from app.db.session import as_utc, make_engine, make_session_factory, upgrade_database, upsert


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{(tmp_path / 'db' / 'test.db').as_posix()}")
    upgrade_database(eng)
    yield eng
    eng.dispose()


def test_migrations_create_the_model_schema(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) >= {
        "series",
        "observations",
        "source_status",
        "mspd_securities",
        "alembic_version",
    }
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models and migrations disagree: {diff}"


def test_upgrade_is_idempotent(engine: Engine) -> None:
    upgrade_database(engine)  # already at head: no error, no change


def test_upsert_inserts_updates_and_chunks(engine: Engine) -> None:
    sessions = make_session_factory(engine)
    when = datetime(2026, 10, 19, tzinfo=UTC)
    start = date(2000, 1, 1)
    rows = [
        {
            "series_id": "s",
            "date": start + timedelta(days=i),
            "value": float(i),
            "source": "test",
            "fetched_at": when,
            "quality": "SEED",
        }
        for i in range(12_000)  # more than one chunk at six columns per row
    ]
    with sessions.begin() as session:
        assert upsert(session, Observation, rows) == 12_000
    with sessions.begin() as session:
        upsert(session, Observation, [{**rows[0], "value": -1.0, "quality": "LIVE"}])
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 12_000
        first = session.get(Observation, ("s", start))
        assert first is not None
        assert (first.value, first.quality) == (-1.0, "LIVE")
        assert as_utc(first.fetched_at) == when  # SQLite drops tzinfo; as_utc restores it
