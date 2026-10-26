from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SeriesRow(Base):
    """Metadata for every time series the terminal knows about."""

    __tablename__ = "series"

    series_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    units: Mapped[str] = mapped_column(String(40))
    frequency: Mapped[str] = mapped_column(String(1))


class Observation(Base):
    """One value of one series on one date, with where and when it came from."""

    __tablename__ = "observations"

    series_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quality: Mapped[str] = mapped_column(String(16))
    """``LIVE`` for rows fetched from the source, ``SEED`` for rows loaded from the snapshot."""


class SourceStatusRow(Base):
    """Health of each upstream source; drives the CACHED/STALE badges."""

    __tablename__ = "source_status"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str] = mapped_column(Text, default="")
    rows: Mapped[int] = mapped_column(Integer, default=0)


class ScenarioRow(Base):
    """A saved scenario (SAVE name): a run's seed and start, and the commands that changed it."""

    __tablename__ = "scenarios"

    name: Mapped[str] = mapped_column(String(24), primary_key=True)
    seed: Mapped[int] = mapped_column(Integer)
    started: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    """Simulated time at which the run began."""
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    """Simulated time when it was saved: LOAD runs the scenario up to here."""
    us_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    india_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    commands: Mapped[str] = mapped_column(Text)
    """JSON: ``[{"at": ISO time, "text": "HIKE 25BP"}, …]`` in the order they ran."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    """Wall-clock time of the save."""


class MspdSecurity(Base):
    """Monthly Statement of the Public Debt, table 3: one row per marketable security issue."""

    __tablename__ = "mspd_securities"

    record_date: Mapped[date] = mapped_column(Date, primary_key=True)
    cusip: Mapped[str] = mapped_column(String(12), primary_key=True)
    issue_date: Mapped[date] = mapped_column(Date, primary_key=True)
    security_class: Mapped[str] = mapped_column(String(64))
    maturity_date: Mapped[date] = mapped_column(Date, index=True)
    interest_rate_pct: Mapped[float | None] = mapped_column(Float)
    yield_pct: Mapped[float | None] = mapped_column(Float)
    issued_musd: Mapped[float | None] = mapped_column(Float)
    outstanding_musd: Mapped[float | None] = mapped_column(Float)
    """Outstanding amount for the whole CUSIP; Treasury reports it on the CUSIP's first row only."""
    quality: Mapped[str] = mapped_column(String(16))
