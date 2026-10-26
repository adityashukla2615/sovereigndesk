# syntax=docker/dockerfile:1
# Build from the repo root (the backend needs ../engine and ../data/seed):
#   docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SD_DATA_DIR=/srv/data

RUN useradd --create-home --uid 10001 sovereign
WORKDIR /srv

COPY engine/ engine/
COPY backend/ backend/
RUN pip install ./engine "./backend[postgres,redis]"
COPY data/seed/ data/seed/
COPY data/replays/ data/replays/
RUN mkdir -p data/cache && chown sovereign data/cache

WORKDIR /srv/backend
USER sovereign
EXPOSE 8000

# The first boot applies migrations and loads the seed snapshot before serving.
HEALTHCHECK --interval=10s --timeout=3s --start-period=90s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
