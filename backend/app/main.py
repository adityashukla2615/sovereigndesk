"""ASGI entry point: ``uvicorn app.main:app``."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app as app_pkg
from app import api
from app.config import get_settings
from app.logs import configure_logging
from app.ws import endpoint

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info(
        "SovereignDesk %s starting (env=%s, offline=%s, fred_key=%s)",
        app_pkg.__version__,
        settings.env,
        settings.offline,
        "set" if settings.fred_api_key else "missing",
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="SovereignDesk API",
        version=app_pkg.__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    application.include_router(api.router)
    application.include_router(endpoint.router)
    return application


app = create_app()
