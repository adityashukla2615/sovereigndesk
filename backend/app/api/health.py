from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import app
import sovereign_engine
from app.api.deps import get_app_settings
from app.config import Settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    engine_version: str
    time: datetime
    offline: bool
    fred_key_configured: bool


@router.get("/health", operation_id="getHealth")
def health(settings: Annotated[Settings, Depends(get_app_settings)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=app.__version__,
        engine_version=sovereign_engine.__version__,
        time=datetime.now(UTC),
        offline=settings.offline,
        fred_key_configured=settings.fred_api_key is not None,
    )
