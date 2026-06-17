"""UseCase module — MCP server for Core API DTO-driven business methods.

Provides an independent MCP server that exposes UseCaseService methods
to AI agents via four-layer progressive disclosure.
"""

from nexusx.use_case.business import UseCaseService, get_return_type
from nexusx.use_case.cli import create_use_case_cli
from nexusx.use_case.context import FromContext
from nexusx.use_case.flat_server import create_use_case_flat_server
from nexusx.use_case.grpc_server import create_use_case_grpc_server
from nexusx.use_case.jsonrpc import create_jsonrpc_router
from nexusx.use_case.router import create_router
from nexusx.use_case.selection import SelectionError
from nexusx.use_case.server import create_use_case_mcp_server
from nexusx.use_case.types import UseCaseAppConfig

__all__ = [
    "create_use_case_cli",
    "create_use_case_flat_server",
    "create_use_case_grpc_server",
    "create_jsonrpc_router",
    "create_router",
    "create_use_case_mcp_server",
    "get_return_type",
    "UseCaseService",
    "UseCaseAppConfig",
    "FromContext",
    "SelectionError",
]
