"""HTTP fetching with retries, an on-disk raw cache, and secrets kept out of both.

The cache key is built from the URL and its non-secret parameters, so an API key never
reaches a file name, a cache file or a log line. A failed live request falls back to the most
recent good raw response for the same request, which the caller then marks CACHED.
"""

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx2
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import WaitBaseT

from app.data.errors import SourceError
from app.logs import redact

log = logging.getLogger(__name__)

SECRET_PARAMS = frozenset({"api_key"})


@dataclass(frozen=True, slots=True)
class FetchedBody:
    content: bytes
    url: str
    """Request URL without secret parameters."""
    fetched_at: datetime
    from_cache: bool


class RawCache:
    """Raw response bodies under ``<root>/<source>/<key>.bin`` with a JSON sidecar."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _paths(self, source: str, key: str) -> tuple[Path, Path]:
        folder = self.root / source
        return folder / f"{key}.bin", folder / f"{key}.json"

    def write(self, source: str, key: str, content: bytes, url: str, fetched_at: datetime) -> None:
        body, meta = self._paths(source, key)
        body.parent.mkdir(parents=True, exist_ok=True)
        for path, data in (
            (body, content),
            (meta, json.dumps({"url": url, "fetched_at": fetched_at.isoformat()}).encode()),
        ):
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)

    def read(self, source: str, key: str) -> FetchedBody | None:
        body, meta = self._paths(source, key)
        if not (body.exists() and meta.exists()):
            return None
        info = json.loads(meta.read_text("utf-8"))
        return FetchedBody(
            content=body.read_bytes(),
            url=info["url"],
            fetched_at=datetime.fromisoformat(info["fetched_at"]),
            from_cache=True,
        )


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx2.TransportError):
        return True
    if isinstance(exc, httpx2.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class Fetcher:
    def __init__(
        self,
        client: httpx2.Client,
        cache: RawCache,
        *,
        attempts: int = 4,
        wait: WaitBaseT | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.cache = cache
        self.attempts = attempts
        self.wait = wait or wait_exponential(multiplier=0.5, max=8.0)
        self.clock = clock
        self.sleep = sleep

    @staticmethod
    def public_url(url: str, params: Mapping[str, str] | None) -> str:
        public = {k: v for k, v in (params or {}).items() if k not in SECRET_PARAMS}
        return f"{url}?{urlencode(sorted(public.items()))}" if public else url

    def get(self, source: str, url: str, params: Mapping[str, str] | None = None) -> FetchedBody:
        public = self.public_url(url, params)
        key = hashlib.sha256(public.encode()).hexdigest()[:32]
        retrying = Retrying(
            stop=stop_after_attempt(self.attempts),
            wait=self.wait,
            retry=retry_if_exception(_retryable),
            reraise=False,
            sleep=self.sleep,
        )
        try:
            response = retrying(self._request, url, params)
        except (RetryError, httpx2.HTTPError) as exc:
            cause = exc.last_attempt.exception() if isinstance(exc, RetryError) else exc
            reason = redact(f"{type(cause).__name__}: {cause}")
            cached = self.cache.read(source, key)
            if cached is None:
                raise SourceError(f"{source}: {reason} (no cached copy)") from None
            log.warning("%s: live fetch failed (%s); using cached copy of %s", source, reason, public)
            return cached
        fetched_at = self.clock()
        self.cache.write(source, key, response.content, public, fetched_at)
        return FetchedBody(response.content, public, fetched_at, from_cache=False)

    def _request(self, url: str, params: Mapping[str, str] | None) -> httpx2.Response:
        response = self.client.get(url, params=dict(params or {}))
        response.raise_for_status()
        return response
