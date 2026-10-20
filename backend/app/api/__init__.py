"""REST API, mounted under ``/api``."""

from fastapi import APIRouter

from app.api import data, health, impact, sim

router = APIRouter(prefix="/api")
router.include_router(health.router)
router.include_router(data.router)
router.include_router(sim.router)
router.include_router(impact.router)

__all__ = ["router"]
