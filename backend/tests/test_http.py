from pathlib import Path

import httpx2
import pytest

from app.data.sources.base import SourceError
from tests.support import make_fetcher

URL = "https://api.example.test/obs"
SECRET = "fake" * 8


def test_retries_transient_failures_then_succeeds(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(503 if len(calls) < 3 else 200, content=b"ok")

    body = make_fetcher(handler, tmp_path).get("test", URL)
    assert (body.content, body.from_cache, len(calls)) == (b"ok", False, 3)


def test_client_errors_are_not_retried(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(404)

    with pytest.raises(SourceError, match="no cached copy"):
        make_fetcher(handler, tmp_path).get("test", URL)
    assert len(calls) == 1


def test_falls_back_to_the_last_good_response(tmp_path: Path) -> None:
    up = True

    def handler(request: httpx2.Request) -> httpx2.Response:
        if not up:
            raise httpx2.ConnectError("connection refused")
        return httpx2.Response(200, content=b"v1")

    fetcher = make_fetcher(handler, tmp_path)
    first = fetcher.get("test", URL, {"series_id": "X"})
    up = False
    second = fetcher.get("test", URL, {"series_id": "X"})
    assert second.content == b"v1"
    assert second.from_cache
    assert second.fetched_at == first.fetched_at
    with pytest.raises(SourceError, match="ConnectError"):
        fetcher.get("test", URL, {"series_id": "never-fetched"})


def test_secrets_never_reach_the_cache_or_errors(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if "fail" in str(request.url):
            raise httpx2.ConnectError(f"cannot reach {request.url}")
        return httpx2.Response(200, content=b"payload")

    fetcher = make_fetcher(handler, tmp_path)
    a = fetcher.get("fred", URL, {"series_id": "DGS10", "api_key": SECRET})
    b = fetcher.get("fred", URL, {"series_id": "DGS10", "api_key": "different" * 4})
    assert SECRET not in a.url
    assert a.url == b.url  # the key is not part of the request identity
    for path in tmp_path.rglob("*"):
        assert SECRET not in path.name
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()
    with pytest.raises(SourceError) as excinfo:
        fetcher.get("fred", URL + "/fail", {"api_key": SECRET})
    assert SECRET not in str(excinfo.value)
    assert "api_key=***" in str(excinfo.value)
