"""Helpers shared by the backend tests: mock HTTP, recorded fixtures and tiny seeds."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from tenacity import wait_none

from app.data.catalog import SeriesSpec
from app.data.http import Fetcher, RawCache
from app.data.seed import Manifest, write_manifest, write_series
from app.data.sources.base import Provenance, SeriesFrame, tidy

SOURCES = Path(__file__).parent / "fixtures" / "sources"
SEED_FETCHED = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

Handler = Callable[[httpx2.Request], httpx2.Response]


def fixture_bytes(name: str) -> bytes:
    return (SOURCES / name).read_bytes()


def make_fetcher(handler: Handler, cache_dir: Path, attempts: int = 3) -> Fetcher:
    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return Fetcher(
        client, RawCache(cache_dir), attempts=attempts, wait=wait_none(), sleep=lambda _: None
    )


def query(request: httpx2.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}


def json_response(payload: bytes | dict[str, Any], status: int = 200) -> httpx2.Response:
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return httpx2.Response(status, content=content, headers={"content-type": "application/json"})


def frame(
    spec: SeriesSpec,
    points: list[tuple[date, float]],
    *,
    when: datetime = SEED_FETCHED,
    from_cache: bool = False,
) -> SeriesFrame:
    provenance = Provenance(spec.source, f"https://example.test/{spec.remote}", when, from_cache)
    return SeriesFrame(spec, tidy(points), provenance)


def write_seed(seed_dir: Path, frames: list[SeriesFrame]) -> None:
    entries = [write_series(seed_dir, f) for f in frames]
    write_manifest(seed_dir, Manifest(SEED_FETCHED.isoformat(), entries, []))
