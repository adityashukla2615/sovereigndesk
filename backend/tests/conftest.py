from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    # Never read backend/.env in tests: it holds the real FRED key.
    return Settings(_env_file=None, env="test", fred_api_key=None)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as test_client:
        yield test_client
