"""ASGI entry point: ``uvicorn app.main:app``."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import app as app_pkg
from app import api
from app.config import Settings, get_settings
from app.data.scheduler import build_scheduler
from app.data.service import DataService
from app.data.sources import build_adapters, make_client
from app.db.session import make_engine, make_session_factory, upgrade_database
from app.logs import configure_logging
from app.sim.simulator import Simulator
from app.ws import endpoint

log = logging.getLogger(__name__)


def _lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        log.info(
            "SovereignDesk %s starting (env=%s, offline=%s, fred_key=%s)",
            app_pkg.__version__,
            settings.env,
            settings.offline,
            "set" if settings.fred_api_key else "missing",
        )
        engine = make_engine(settings.database_url)
        await run_in_threadpool(upgrade_database, engine)
        client = make_client(settings)
        service = DataService(
            settings, make_session_factory(engine), build_adapters(settings, client)
        )
        await run_in_threadpool(service.bootstrap)
        application.state.data = service
        sim = Simulator(service, seed=settings.sim_seed)
        await run_in_threadpool(sim.load)
        application.state.sim = sim
        if settings.sim_enabled:
            sim.start()

        scheduler = None
        if settings.scheduler_enabled and not settings.offline:
            scheduler = build_scheduler(service)
            scheduler.start()
        try:
            yield
        finally:
            await sim.stop()
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            client.close()
            engine.dispose()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    application = FastAPI(
        title="SovereignDesk API",
        version=app_pkg.__version__,
        lifespan=_lifespan(settings),
    )
    application.state.settings = settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    application.include_router(api.router)
    application.include_router(endpoint.router)
    if settings.static_dir is not None:
        # The one-service image (Render): the terminal itself, after /api and /ws.
        application.mount(
            "/", StaticFiles(directory=settings.static_dir, html=True), name="terminal"
        )
    return application


app = create_app()
