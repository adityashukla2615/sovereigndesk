"""REST API, mounted under ``/api``."""

from fastapi import APIRouter

from app.api import data, health

router = APIRouter(prefix="/api")
router.include_router(health.router)
router.include_router(data.router)

__all__ = ["router"]
