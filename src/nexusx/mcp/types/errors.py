"""Error types for MCP tools."""

from __future__ import annotations

from enum import Enum
from typing import Any


class MCPErrors(str, Enum):
    """Error types for MCP tool responses."""

    # Query building errors
    INVALID_FIELD_PATH = "invalid_field_path"
    INVALID_OPERATION = "invalid_operation"
    MISSING_REQUIRED_FIELD = "missing_required_field"

    # Execution errors
    QUERY_EXECUTION_ERROR = "query_execution_error"
    MUTATION_EXECUTION_ERROR = "mutation_execution_error"

    # Schema errors
    SCHEMA_NOT_FOUND = "schema_not_found"
    TYPE_NOT_FOUND = "type_not_found"

    # Multi-app errors
    APP_NOT_FOUND = "app_not_found"
    APP_NAME_REQUIRED = "app_name_required"
    INVALID_APP_MODE = "invalid_app_mode"

    # UseCase compose MCP — service/method lookup within an app
    SERVICE_NOT_FOUND = "service_not_found"
    METHOD_NOT_FOUND = "method_not_found"

    # General errors
    INTERNAL_ERROR = "internal_error"
    VALIDATION_ERROR = "validation_error"


class MCPError(Exception):
    """Custom exception for MCP tool errors.

    Attributes:
        error_type: The type of error from MCPErrors enum.
        message: Human-readable error message.
    """

    def __init__(self, error_type: MCPErrors, message: str):
        """Initialize MCP error.

        Args:
            error_type: The type of error.
            message: Human-readable error message.
        """
        self.error_type = error_type
        self.message = message
        super().__init__(message)


def create_error_response(
    error: MCPError | str,
    error_type: MCPErrors | None = None,
) -> dict[str, Any]:
    """Create a structured error response.

    Args:
        error: Either an MCPError instance or an error message string.
        error_type: Error type (required if error is a string).

    Returns:
        Dictionary with success, error, and error_type fields.
    """
    if isinstance(error, MCPError):
        return {
            "success": False,
            "error": error.message,
            "error_type": error.error_type.value,
        }

    if error_type is None:
        error_type = MCPErrors.INTERNAL_ERROR

    return {
        "success": False,
        "error": error,
        "error_type": error_type.value,
    }


def create_success_response(data: Any) -> dict[str, Any]:
    """Create a structured success response.

    Args:
        data: The response data.

    Returns:
        Dictionary with success and data fields.
    """
    return {
        "success": True,
        "data": data,
    }
