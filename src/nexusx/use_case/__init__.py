"""UseCase module — MCP server for Core API DTO-driven business methods.

Provides an independent MCP server that exposes UseCaseService methods
to AI agents via four-layer progressive disclosure.
"""

from nexusx.use_case.business import UseCaseService
from nexusx.use_case.context import FromContext
from nexusx.use_case.flat_server import create_flat_mcp_server
from nexusx.use_case.jsonrpc import create_jsonrpc_router
from nexusx.use_case.router import create_router
from nexusx.use_case.selection import SelectionError
from nexusx.use_case.server import create_use_case_mcp_server
from nexusx.use_case.types import UseCaseAppConfig


def __getattr__(name: str):
    if name == "create_cli":
        from nexusx.use_case.cli import create_cli
        return create_cli
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "create_cli",
    "create_flat_mcp_server",
    "create_jsonrpc_router",
    "create_router",
    "create_use_case_mcp_server",
    "UseCaseService",
    "UseCaseAppConfig",
    "FromContext",
    "SelectionError",
]
