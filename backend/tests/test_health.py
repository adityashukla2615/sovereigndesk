from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

import app
import sovereign_engine
from app.config import Settings
from app.main import create_app


def test_health_reports_versions(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == app.__version__
    assert body["engine_version"] == sovereign_engine.__version__
    assert body["fred_key_configured"] is False
    assert datetime.fromisoformat(body["time"]).tzinfo is not None


def test_openapi_exposes_health(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/health"]["get"]["operationId"] == "getHealth"


def test_the_one_service_image_serves_the_terminal_beside_the_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>SovereignDesk</title>", encoding="utf-8")
    settings = Settings(_env_file=None, env="test", fred_api_key=None, static_dir=tmp_path)
    plain = TestClient(create_app(settings))  # no lifespan: only routing is under test
    assert "<title>SovereignDesk</title>" in plain.get("/").text
    assert plain.get("/api/health").json()["status"] == "ok"  # the API still comes first
    assert plain.get("/nope.js").status_code == 404
