"""Terminal function codes: parsing, the registry (single source of truth) and handlers."""

from app.commands import (  # noqa: F401 - importing registers the handlers
    impact,
    india,
    linkage,
    replay,
    scenario,
    system,
    us,
)
from app.commands.registry import REGISTRY, CommandResult, catalog, execute

__all__ = ["REGISTRY", "CommandResult", "catalog", "execute"]
