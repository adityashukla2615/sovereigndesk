"""Terminal function codes: parsing, the registry (single source of truth) and handlers."""

from app.commands import india, planned, system, us  # noqa: F401 - importing registers the handlers
from app.commands.registry import REGISTRY, CommandResult, catalog, execute

__all__ = ["REGISTRY", "CommandResult", "catalog", "execute"]
