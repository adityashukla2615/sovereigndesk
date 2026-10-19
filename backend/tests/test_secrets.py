import logging

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.logs import RedactingFilter, redact

# Low-entropy and not hex, so neither `tasks.py check-secrets` nor gitleaks mistakes it for a key.
FAKE_KEY = "fake" * 8


@pytest.mark.parametrize(
    "text",
    [
        f"GET https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={FAKE_KEY}&file_type=json",
        f"FRED_API_KEY={FAKE_KEY}",
        f"Api_Key={FAKE_KEY} trailing",
    ],
)
def test_redact_removes_keys(text: str) -> None:
    cleaned = redact(text)
    assert FAKE_KEY not in cleaned
    assert "=***" in cleaned


def test_filter_redacts_args(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.redaction")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="test.redaction"):
        logger.info("fetching %s", f"https://example.test/?api_key={FAKE_KEY}")
    assert FAKE_KEY not in caplog.text
    assert "api_key=***" in caplog.text


def test_settings_never_reveal_the_key() -> None:
    settings = Settings(_env_file=None, fred_api_key=SecretStr(FAKE_KEY))
    assert FAKE_KEY not in repr(settings)
    assert FAKE_KEY not in settings.model_dump_json()
    assert settings.fred_api_key is not None
    assert settings.fred_api_key.get_secret_value() == FAKE_KEY


def test_fred_key_reads_the_unprefixed_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", FAKE_KEY)
    settings = Settings(_env_file=None)
    assert settings.fred_api_key is not None
    assert settings.fred_api_key.get_secret_value() == FAKE_KEY
