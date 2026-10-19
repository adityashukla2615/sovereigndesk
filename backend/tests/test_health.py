from datetime import datetime

from fastapi.testclient import TestClient

import app
import sovereign_engine


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
