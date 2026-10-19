"""Engine, sessions, migrations and dialect-portable upserts."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, Executable, Table, create_engine, event
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True, pool_pre_ping=True)
    if parsed.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def upgrade_database(engine: Engine) -> None:
    """Apply every Alembic migration (``alembic upgrade head``) on the given engine."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def upsert(session: Session, model: type[Base], rows: Iterable[Mapping[str, Any]]) -> int:
    """Insert rows, replacing every non-key column of rows whose primary key already exists."""
    batch = [dict(r) for r in rows]
    if not batch:
        return 0
    table = cast(Table, model.__table__)
    keys = [c.name for c in table.primary_key.columns]
    columns = [c for c in batch[0] if c not in keys]
    dialect = session.get_bind().dialect.name
    # One statement, compiled once, executed with the whole parameter list (DB-API
    # executemany). Building a multi-row VALUES clause instead is far slower to compile.
    if dialect == "sqlite":
        lite = sqlite.insert(table)
        stmt: Executable = lite.on_conflict_do_update(
            index_elements=keys, set_={c: lite.excluded[c] for c in columns}
        )
    elif dialect == "postgresql":
        pg = postgresql.insert(table)
        stmt = pg.on_conflict_do_update(
            index_elements=keys, set_={c: pg.excluded[c] for c in columns}
        )
    else:
        raise NotImplementedError(f"upsert is not implemented for {dialect}")
    session.execute(stmt, batch)
    return len(batch)


def as_utc(moment: datetime) -> datetime:
    """SQLite drops timezone info; every stored timestamp is UTC, so restore it on read."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def as_utc_or_none(moment: datetime | None) -> datetime | None:
    return None if moment is None else as_utc(moment)


__all__ = [
    "Base",
    "as_utc",
    "as_utc_or_none",
    "make_engine",
    "make_session_factory",
    "upgrade_database",
    "upsert",
]
