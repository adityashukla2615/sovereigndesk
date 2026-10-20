"""The data service: seed bootstrap, refreshes, quality tags and reads for the API/simulator."""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.data.catalog import STATIC_SERIES, SeriesSpec
from app.data.quality import LIVE_WINDOW, Quality, classify, quality_label
from app.data.seed import fetched_at, read_manifest, read_mspd, read_series
from app.data.sources.base import Adapter, FetchOutcome, SeriesFrame, SourceError
from app.data.sources.fiscaldata import FiscalDataAdapter, MspdRow, MspdSnapshot
from app.db.models import MspdSecurity, Observation, SeriesRow, SourceStatusRow
from app.db.session import as_utc, as_utc_or_none, upsert
from app.logs import redact

log = logging.getLogger(__name__)

REFRESH_LOOKBACK = timedelta(days=730)
"""Refreshes re-fetch two years so revisions land; full history comes from the seed."""
SOURCE_LOOKBACK: Mapping[str, timedelta] = {
    "rbi": timedelta(days=7),
    "fbil": timedelta(days=30),
    "fbil_gsec": timedelta(days=14),
}
"""Shorter windows for page-by-page sources, so a daily refresh never crawls RBI's archive."""


@dataclass(frozen=True, slots=True)
class SeriesInfo:
    series_id: str
    source: str
    title: str
    units: str
    frequency: str
    quality: Quality
    label: str
    as_of: date | None
    last_value: float | None
    rows: int


@dataclass(frozen=True, slots=True)
class SeriesView:
    info: SeriesInfo
    dates: list[date]
    values: list[float]


@dataclass(frozen=True, slots=True)
class SourceInfo:
    source: str
    status: str
    """``never``, ``ok``, ``partial`` (some series failed), ``cached`` or ``error``."""
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    message: str
    rows: int


@dataclass(frozen=True, slots=True)
class RefreshReport:
    source: str
    status: str
    rows: int
    errors: dict[str, str]


def _spec_row(spec: SeriesSpec) -> dict[str, str]:
    return {
        "series_id": spec.series_id,
        "source": spec.source,
        "title": spec.title,
        "units": spec.units,
        "frequency": spec.frequency,
    }


def _observations(
    series_id: str, source: str, frame: pd.DataFrame, when: datetime, quality: Quality
) -> Iterable[dict[str, object]]:
    for day, value in zip(frame["date"], frame["value"], strict=True):
        yield {
            "series_id": series_id,
            "date": day,
            "value": float(value),
            "source": source,
            "fetched_at": when,
            "quality": quality.value,
        }


def _mspd_row(row: MspdRow, quality: Quality) -> dict[str, object]:
    return {
        "record_date": row.record_date,
        "cusip": row.cusip,
        "issue_date": row.issue_date,
        "security_class": row.security_class,
        "maturity_date": row.maturity_date,
        "interest_rate_pct": row.interest_rate_pct,
        "yield_pct": row.yield_pct,
        "issued_musd": row.issued_musd,
        "outstanding_musd": row.outstanding_musd,
        "quality": quality.value,
    }


def _latest_rows(series_ids: Iterable[str] | None) -> Select[Observation]:
    """The newest observation of each series (optionally restricted to ``series_ids``)."""
    newest = select(Observation.series_id, func.max(Observation.date).label("last"))
    if series_ids is not None:
        newest = newest.where(Observation.series_id.in_(list(series_ids)))
    sub = newest.group_by(Observation.series_id).subquery()
    return select(Observation).join(
        sub, (Observation.series_id == sub.c.series_id) & (Observation.date == sub.c.last)
    )


class DataService:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker[Session],
        adapters: Mapping[str, Adapter],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.adapters = dict(adapters)
        self.clock = clock

    # ------------------------------------------------------------------ bootstrap

    def bootstrap(self) -> int:
        """Register the catalog and load the seed for every series that has no rows yet."""
        loaded = 0
        with self.sessions.begin() as session:
            upsert(session, SeriesRow, (_spec_row(s) for s in STATIC_SERIES))
            manifest = read_manifest(self.settings.seed_dir)
            if manifest is None:
                log.warning("no seed manifest in %s; series start empty", self.settings.seed_dir)
                return 0
            present = set(session.scalars(select(Observation.series_id).distinct()))
            for entry in manifest.series:
                if entry.series_id in present:
                    continue
                frame = read_series(self.settings.seed_dir, entry)
                upsert(session, SeriesRow, [_spec_row(entry.spec)])
                rows = _observations(
                    entry.series_id, entry.source, frame, fetched_at(entry), Quality.SEED
                )
                loaded += upsert(session, Observation, rows)
            if session.scalar(select(func.count()).select_from(MspdSecurity)) == 0:
                for table in manifest.tables:
                    securities = read_mspd(self.settings.seed_dir, table)
                    upsert(session, MspdSecurity, (_mspd_row(r, Quality.SEED) for r in securities))
        log.info("seed bootstrap loaded %d observations", loaded)
        return loaded

    # ------------------------------------------------------------------ refresh

    def refresh(self, source: str) -> RefreshReport:
        """Fetch one source and store what arrived; a failure only marks the source unhealthy."""
        if self.settings.offline:
            return RefreshReport(source, "skipped", 0, {"offline": "offline mode: no network"})
        now = self.clock()
        adapter = self.adapters[source]
        try:
            if source in self.settings.fail_sources:
                raise SourceError(f"{source}: simulated outage (SD_FAIL_SOURCES)")
            outcome = adapter.fetch(
                start=now.date() - SOURCE_LOOKBACK.get(source, REFRESH_LOOKBACK)
            )
        except SourceError as exc:
            message = redact(str(exc))
            log.warning("refresh %s failed: %s", source, message)
            self._set_status(source, "error", now, success=False, message=message, rows=0)
            return RefreshReport(source, "error", 0, {source: message})

        rows = self._store(outcome.frames)
        if isinstance(adapter, FiscalDataAdapter):
            self._refresh_mspd(adapter, outcome)
        from_cache = any(f.provenance.from_cache for f in outcome.frames)
        status = "cached" if from_cache else "partial" if outcome.errors else "ok"
        message = redact("; ".join(f"{k}: {v}" for k, v in outcome.errors.items()))[:2000]
        self._set_status(source, status, now, success=not from_cache, message=message, rows=rows)
        return RefreshReport(source, status, rows, dict(outcome.errors))

    def _refresh_mspd(self, adapter: FiscalDataAdapter, outcome: FetchOutcome) -> None:
        try:
            snapshot: MspdSnapshot = adapter.mspd_latest()
        except SourceError as exc:
            outcome.errors["mspd"] = str(exc)
            return
        with self.sessions.begin() as session:
            upsert(session, MspdSecurity, (_mspd_row(r, Quality.LIVE) for r in snapshot.rows))

    def refresh_stale(self) -> list[RefreshReport]:
        """Refresh every source not fetched successfully within the live window."""
        now = self.clock()
        last_success = {s.source: s.last_success_at for s in self.sources()}
        return [
            self.refresh(source)
            for source in self.adapters
            if (last := last_success.get(source)) is None or now - last > LIVE_WINDOW
        ]

    def _store(self, frames: list[SeriesFrame]) -> int:
        stored = 0
        with self.sessions.begin() as session:
            for frame in frames:
                upsert(session, SeriesRow, [_spec_row(frame.spec)])
                prov = frame.provenance
                rows = _observations(
                    frame.spec.series_id, prov.source, frame.data, prov.fetched_at, Quality.LIVE
                )
                stored += upsert(session, Observation, rows)
        return stored

    def _set_status(
        self, source: str, status: str, now: datetime, *, success: bool, message: str, rows: int
    ) -> None:
        with self.sessions.begin() as session:
            existing = session.get(SourceStatusRow, source)
            previous = as_utc_or_none(existing.last_success_at) if existing else None
            upsert(
                session,
                SourceStatusRow,
                [
                    {
                        "source": source,
                        "status": status,
                        "last_attempt_at": now,
                        "last_success_at": now if success else previous,
                        "message": message,
                        "rows": rows,
                    }
                ],
            )

    # ------------------------------------------------------------------ reads

    def sources(self) -> list[SourceInfo]:
        with self.sessions() as session:
            known = {r.source: r for r in session.scalars(select(SourceStatusRow))}
        out = []
        for source in sorted(set(self.adapters) | set(known)):
            row = known.get(source)
            out.append(
                SourceInfo(
                    source=source,
                    status=row.status if row else "never",
                    last_attempt_at=as_utc_or_none(row.last_attempt_at) if row else None,
                    last_success_at=as_utc_or_none(row.last_success_at) if row else None,
                    message=row.message if row else "",
                    rows=row.rows if row else 0,
                )
            )
        return out

    def series_info(self, series_ids: set[str] | None = None) -> list[SeriesInfo]:
        """Quality, freshness and size of every (or the requested) series."""
        now = self.clock()
        sources = {s.source: s for s in self.sources()}
        with self.sessions() as session:
            counts = select(Observation.series_id, func.count(), func.max(Observation.date))
            metas = select(SeriesRow).order_by(SeriesRow.series_id)
            if series_ids is not None:
                counts = counts.where(Observation.series_id.in_(series_ids))
                metas = metas.where(SeriesRow.series_id.in_(series_ids))
            summary = {
                sid: (int(n), last)
                for sid, n, last in session.execute(counts.group_by(Observation.series_id))
            }
            latest = {o.series_id: o for o in session.scalars(_latest_rows(series_ids))}
            return [
                self._info(
                    meta, summary.get(meta.series_id), latest.get(meta.series_id), sources, now
                )
                for meta in session.scalars(metas)
            ]

    def _info(
        self,
        meta: SeriesRow,
        summary: tuple[int, date] | None,
        last: Observation | None,
        sources: Mapping[str, SourceInfo],
        now: datetime,
    ) -> SeriesInfo:
        source = sources.get(meta.source)
        failing = source is not None and source.status in ("error", "cached")
        last_success = source.last_success_at if source else None
        quality = classify(
            last.quality if last else None, last_success, now, source_failing=failing
        )
        seed_date = as_utc(last.fetched_at).date() if last is not None else None
        return SeriesInfo(
            series_id=meta.series_id,
            source=meta.source,
            title=meta.title,
            units=meta.units,
            frequency=meta.frequency,
            quality=quality,
            label=quality_label(quality, last_success=last_success, seed_date=seed_date, now=now),
            as_of=summary[1] if summary else None,
            last_value=last.value if last else None,
            rows=summary[0] if summary else 0,
        )

    def series(
        self, series_id: str, start: date | None = None, end: date | None = None
    ) -> SeriesView | None:
        infos = self.series_info({series_id})
        if not infos:
            return None
        query = select(Observation.date, Observation.value).where(
            Observation.series_id == series_id
        )
        if start:
            query = query.where(Observation.date >= start)
        if end:
            query = query.where(Observation.date <= end)
        with self.sessions() as session:
            points = session.execute(query.order_by(Observation.date)).all()
        return SeriesView(infos[0], [d for d, _ in points], [float(v) for _, v in points])

    def latest_values(self, series_ids: Iterable[str]) -> dict[str, tuple[date, float]]:
        """Latest (date, value) of each requested series that has data."""
        with self.sessions() as session:
            return {
                o.series_id: (o.date, o.value) for o in session.scalars(_latest_rows(series_ids))
            }

    def mspd(self) -> tuple[list[MspdRow], Quality]:
        """Securities outstanding at the latest MSPD month-end, with the snapshot's quality."""
        with self.sessions() as session:
            latest = session.scalar(select(func.max(MspdSecurity.record_date)))
            if latest is None:
                return [], Quality.MISSING
            rows = session.scalars(
                select(MspdSecurity).where(MspdSecurity.record_date == latest)
            ).all()
        securities = [
            MspdRow(
                record_date=r.record_date,
                cusip=r.cusip,
                issue_date=r.issue_date,
                security_class=r.security_class,
                maturity_date=r.maturity_date,
                interest_rate_pct=r.interest_rate_pct,
                yield_pct=r.yield_pct,
                issued_musd=r.issued_musd,
                outstanding_musd=r.outstanding_musd,
            )
            for r in rows
        ]
        source = next((s for s in self.sources() if s.source == "fiscaldata"), None)
        quality = classify(
            rows[0].quality,
            source.last_success_at if source else None,
            self.clock(),
            source_failing=source is not None and source.status in ("error", "cached"),
        )
        return securities, quality
