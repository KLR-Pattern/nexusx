"""UseCase module — MCP server for Core API DTO-driven business methods.

Provides an independent MCP server that exposes UseCaseService methods
to AI agents via four-layer progressive disclosure.
"""

from nexusx.use_case.business import UseCaseService
from nexusx.use_case.context import FromContext
from nexusx.use_case.router import create_router
from nexusx.use_case.selection import SelectionError
from nexusx.use_case.server import create_use_case_mcp_server
from nexusx.use_case.types import UseCaseAppConfig

__all__ = [
    "create_router",
    "create_use_case_mcp_server",
    "UseCaseService",
    "UseCaseAppConfig",
    "FromContext",
    "SelectionError",
]
