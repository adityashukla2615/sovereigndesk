"""FRED (Federal Reserve Bank of St. Louis) series observations API."""

import json
from datetime import date

from pydantic import SecretStr

from app.data.catalog import FRED_SERIES, SeriesSpec
from app.data.http import Fetcher
from app.data.sources.base import FetchOutcome, Provenance, SeriesFrame, SourceError, tidy

OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


def parse_observations(content: bytes) -> list[tuple[date, float]]:
    """FRED marks missing observations with ``"."``; those are dropped."""
    payload = json.loads(content)
    if "observations" not in payload:
        raise SourceError(f"fred: unexpected response: {str(payload)[:200]}")
    return [
        (date.fromisoformat(obs["date"]), float(obs["value"]))
        for obs in payload["observations"]
        if obs["value"] not in (".", "")
    ]


class FredAdapter:
    source = "fred"

    def __init__(
        self,
        fetcher: Fetcher,
        api_key: SecretStr | None,
        specs: tuple[SeriesSpec, ...] = FRED_SERIES,
    ) -> None:
        self.fetcher = fetcher
        self.api_key = api_key
        self.specs = specs

    def fetch(
        self, series_ids: set[str] | None = None, start: date | None = None, end: date | None = None
    ) -> FetchOutcome:
        if self.api_key is None:
            raise SourceError("fred: FRED_API_KEY is not configured (see backend/.env.example)")
        outcome = FetchOutcome()
        for spec in self.specs:
            if series_ids is not None and spec.series_id not in series_ids:
                continue
            params = {
                "series_id": spec.remote,
                "api_key": self.api_key.get_secret_value(),
                "file_type": "json",
            }
            if start:
                params["observation_start"] = start.isoformat()
            if end:
                params["observation_end"] = end.isoformat()
            try:
                body = self.fetcher.get(self.source, OBSERVATIONS_URL, params)
                points = parse_observations(body.content)
            except (SourceError, ValueError, KeyError) as exc:
                outcome.errors[spec.series_id] = str(exc)
                continue
            provenance = Provenance(self.source, body.url, body.fetched_at, body.from_cache)
            outcome.frames.append(SeriesFrame(spec, tidy(points), provenance))
        if not outcome.frames and outcome.errors:
            raise SourceError(f"fred: every series failed, e.g. {next(iter(outcome.errors.values()))}")
        return outcome
