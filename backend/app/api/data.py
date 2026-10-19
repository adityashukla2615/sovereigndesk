"""Data health and series access: ``/api/data/status`` and ``/api/data/series/{id}``."""

from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_app_settings, get_data_service
from app.config import Settings
from app.data.quality import Quality
from app.data.service import DataService, SeriesInfo

router = APIRouter(prefix="/data", tags=["data"])


class SourceStatus(BaseModel):
    source: str
    status: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    message: str
    rows: int


class SeriesStatus(BaseModel):
    series_id: str
    source: str
    title: str
    units: str
    frequency: str
    quality: Quality
    label: str
    """Badge text, e.g. ``LIVE``, ``CACHED 3d``, ``SEED 2026-10-19``."""
    as_of: date | None
    last_value: float | None
    rows: int


class DataStatus(BaseModel):
    generated_at: datetime
    offline: bool
    sources: list[SourceStatus]
    series: list[SeriesStatus]
    quality_counts: dict[str, int]


class SeriesData(BaseModel):
    meta: SeriesStatus
    dates: list[date]
    values: list[float]


def _status(info: SeriesInfo) -> SeriesStatus:
    return SeriesStatus(
        series_id=info.series_id,
        source=info.source,
        title=info.title,
        units=info.units,
        frequency=info.frequency,
        quality=info.quality,
        label=info.label,
        as_of=info.as_of,
        last_value=info.last_value,
        rows=info.rows,
    )


@router.get("/status", operation_id="getDataStatus")
def data_status(
    service: Annotated[DataService, Depends(get_data_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> DataStatus:
    series = [_status(i) for i in service.series_info()]
    counts: dict[str, int] = {}
    for s in series:
        counts[s.quality.value] = counts.get(s.quality.value, 0) + 1
    return DataStatus(
        generated_at=datetime.now(UTC),
        offline=settings.offline,
        sources=[SourceStatus(**asdict(s)) for s in service.sources()],
        series=series,
        quality_counts=counts,
    )


@router.get("/series/{series_id:path}", operation_id="getSeries")
def series_data(
    series_id: str,
    service: Annotated[DataService, Depends(get_data_service)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> SeriesData:
    view = service.series(series_id, start, end)
    if view is None:
        raise HTTPException(status_code=404, detail=f"unknown series {series_id!r}")
    return SeriesData(meta=_status(view.info), dates=view.dates, values=view.values)
