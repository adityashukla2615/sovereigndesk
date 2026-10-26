# syntax=docker/dockerfile:1
# One service with everything: the terminal, built, served by the API on the same origin. This
# is what Render runs (render.yaml); `docker compose` keeps the backend and nginx apart instead.
#   docker build -t sovereigndesk . && docker run -p 10000:10000 sovereigndesk

FROM node:24-alpine AS terminal
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SD_DATA_DIR=/srv/data \
    SD_STATIC_DIR=/srv/terminal \
    SD_MODEL_CACHE_DIR=/srv/backend/var/models \
    SD_OFFLINE=true \
    SD_SCHEDULER_ENABLED=false \
    SD_ENV=prod

RUN useradd --create-home --uid 10001 sovereign
WORKDIR /srv

COPY engine/ engine/
COPY backend/ backend/
RUN pip install ./engine ./backend
COPY data/seed/ data/seed/
COPY data/replays/ data/replays/
COPY --from=terminal /app/dist/ terminal/

# Load the seed into the SQLite database at build time: a free instance then starts in seconds
# of loading instead of minutes each time it wakes. Fit the MPC predictor here too: on a tenth
# of a CPU its first fit would stall every command for over a minute.
WORKDIR /srv/backend
RUN python -c "from app.config import get_settings; \
from app.data.service import DataService; \
from app.db.session import make_engine, make_session_factory, upgrade_database; \
s = get_settings(); e = make_engine(s.database_url); upgrade_database(e); \
DataService(s, make_session_factory(e), {}).bootstrap(); e.dispose()" \
 && python -m app.sim.model_cache \
 && mkdir -p /srv/data/cache \
 && chown -R sovereign /srv/backend/var /srv/data/cache
USER sovereign

# Render routes public traffic to $PORT (10000 unless set).
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips '*'"]
