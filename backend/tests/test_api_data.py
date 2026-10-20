from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.data.catalog import SeriesSpec
from app.main import create_app
from tests.support import frame, write_seed

TEN = SeriesSpec("ust/par/10Y", "treasury", "10 Yr", "Treasury par yield, 10Y", "%", "D")
JAPAN = SeriesSpec(
    "tic/japan", "tic", "Japan", "Foreign holdings of Treasuries: Japan", "USD bn", "M"
)


@pytest.fixture
def seeded(settings: Settings) -> Iterator[TestClient]:
    write_seed(
        settings.seed_dir,
        [
            frame(TEN, [(date(2026, 10, 15), 5.10), (date(2026, 10, 16), 5.09)]),
            frame(JAPAN, [(date(2026, 7, 31), 1103.9), (date(2026, 8, 31), 1068.3)]),
        ],
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_status_reports_sources_series_and_seed_badges(seeded: TestClient) -> None:
    body = seeded.get("/api/data/status").json()
    assert body["offline"] is True
    assert {s["source"] for s in body["sources"]} == {
        *("fred", "treasury", "fiscaldata", "tic"),
        *("rbi", "fbil", "fbil_gsec", "nsdl"),
    }
    assert all(s["status"] == "never" for s in body["sources"])
    series = {s["series_id"]: s for s in body["series"]}
    ten = series["ust/par/10Y"]
    assert (ten["quality"], ten["label"], ten["as_of"], ten["last_value"]) == (
        "SEED",
        "SEED 2026-10-19",
        "2026-10-16",
        5.09,
    )
    assert series["tic/japan"]["rows"] == 2  # dynamic TIC series are registered from the seed
    assert series["fred/DGS10"]["quality"] == "MISSING"
    assert body["quality_counts"]["SEED"] == 2


def test_series_endpoint_with_slashes_and_range(seeded: TestClient) -> None:
    body = seeded.get("/api/data/series/ust/par/10Y").json()
    assert body["dates"] == ["2026-10-15", "2026-10-16"]
    assert body["values"] == [5.10, 5.09]
    assert body["meta"]["units"] == "%"
    ranged = seeded.get("/api/data/series/tic/japan", params={"start": "2026-08-01"}).json()
    assert ranged["values"] == [1068.3]


def test_unknown_series_is_404(seeded: TestClient) -> None:
    response = seeded.get("/api/data/series/fred/NOPE")
    assert response.status_code == 404
