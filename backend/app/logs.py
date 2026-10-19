"""Logging setup with a filter that redacts API keys before any handler formats a record."""

import logging
import re

# `api_key=...` in query strings (FRED puts the key there) and `FRED_API_KEY=...` style assignments.
_SECRET_PATTERN = re.compile(r"(?i)\b((?:fred_)?api_key)=([^&\s'\"]+)")
_REDACTED = r"\1=***"


def redact(text: str) -> str:
    return _SECRET_PATTERN.sub(_REDACTED, text)


class RedactingFilter(logging.Filter):
    """Rewrites the fully formatted message so secrets passed as args are caught too."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # These loggers get their own filter because uvicorn attaches handlers that bypass root's,
    # and httpx logs every request URL (query string included) at INFO.
    for name in ("httpx", "httpx2", "httpcore", "uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in logger.filters):
            logger.addFilter(RedactingFilter())
