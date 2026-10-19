"""Request-scoped access to app-wide objects created in the lifespan."""

from fastapi import HTTPException, Request

from app.config import Settings
from app.data.service import DataService


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_data_service(request: Request) -> DataService:
    service: DataService | None = getattr(request.app.state, "data", None)
    if service is None:
        raise HTTPException(status_code=503, detail="data service is starting")
    return service
