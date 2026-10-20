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
from dataclasses import dataclass, replace
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
    """True when the live request failed and this is the last saved copy (possibly stale)."""


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


def _cache_key(identity: str) -> str:
    return hashlib.sha256(identity.encode()).hexdigest()[:32]


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
        key = _cache_key(public)
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
            log.warning(
                "%s: live fetch failed (%s); using cached copy of %s", source, reason, public
            )
            return cached
        fetched_at = self.clock()
        self.cache.write(source, key, response.content, public, fetched_at)
        return FetchedBody(response.content, public, fetched_at, from_cache=False)

    def post(
        self, source: str, url: str, form: Mapping[str, str], *, key_fields: tuple[str, ...]
    ) -> FetchedBody:
        """Form POST (e.g. an ASP.NET postback). Only ``key_fields`` identify it in the cache,
        because hidden fields such as __VIEWSTATE change on every page load."""
        identity = self.public_url(url, {k: form[k] for k in key_fields if k in form})
        key = _cache_key("POST " + identity)
        retrying = Retrying(
            stop=stop_after_attempt(self.attempts),
            wait=self.wait,
            retry=retry_if_exception(_retryable),
            reraise=False,
            sleep=self.sleep,
        )
        try:
            response = retrying(self._send, url, dict(form))
        except (RetryError, httpx2.HTTPError) as exc:
            cause = exc.last_attempt.exception() if isinstance(exc, RetryError) else exc
            cached = self.cache.read(source, key)
            if cached is None:
                raise SourceError(
                    f"{source}: POST {identity} failed: {redact(str(cause))}"
                ) from None
            return cached
        fetched_at = self.clock()
        self.cache.write(source, key, response.content, identity, fetched_at)
        return FetchedBody(response.content, identity, fetched_at, from_cache=False)

    def post_json(
        self,
        source: str,
        url: str,
        payload: Mapping[str, object],
        *,
        identity: str,
        headers: Mapping[str, str] | None = None,
    ) -> FetchedBody:
        """JSON POST (e.g. a JSON-RPC call). ``identity`` names the request in the cache and the
        provenance, so a per-call field such as a request id does not make every call new."""
        public = f"{url} {identity}"
        key = _cache_key("JSON " + public)
        retrying = Retrying(
            stop=stop_after_attempt(self.attempts),
            wait=self.wait,
            retry=retry_if_exception(_retryable),
            reraise=False,
            sleep=self.sleep,
        )
        try:
            response = retrying(self._send_json, url, payload, dict(headers or {}))
        except (RetryError, httpx2.HTTPError) as exc:
            cause = exc.last_attempt.exception() if isinstance(exc, RetryError) else exc
            cached = self.cache.read(source, key)
            if cached is None:
                raise SourceError(f"{source}: {public} failed: {redact(str(cause))}") from None
            log.warning("%s: live call failed; using cached copy of %s", source, public)
            return cached
        fetched_at = self.clock()
        self.cache.write(source, key, response.content, public, fetched_at)
        return FetchedBody(response.content, public, fetched_at, from_cache=False)

    def saved(
        self, source: str, url: str, params: Mapping[str, str] | None = None
    ) -> FetchedBody | None:
        """The body an earlier live ``get`` of this request saved, for documents that never change
        once published (a press release by id), so they are not downloaded twice. It is a live
        response from its ``fetched_at``, not a fallback, so ``from_cache`` is False."""
        cached = self.cache.read(source, _cache_key(self.public_url(url, params)))
        return None if cached is None else replace(cached, from_cache=False)

    def _request(self, url: str, params: Mapping[str, str] | None) -> httpx2.Response:
        response = self.client.get(url, params=dict(params or {}))
        response.raise_for_status()
        return response

    def _send(self, url: str, form: dict[str, str]) -> httpx2.Response:
        response = self.client.post(url, data=form)
        response.raise_for_status()
        return response

    def _send_json(
        self, url: str, payload: Mapping[str, object], headers: dict[str, str]
    ) -> httpx2.Response:
        response = self.client.post(url, content=json.dumps(payload).encode(), headers=headers)
        response.raise_for_status()
        return response
