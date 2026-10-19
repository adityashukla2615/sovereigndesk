"""REST API, mounted under ``/api``."""

from fastapi import APIRouter

from app.api import data, health, sim

router = APIRouter(prefix="/api")
router.include_router(health.router)
router.include_router(data.router)
router.include_router(sim.router)

__all__ = ["router"]
