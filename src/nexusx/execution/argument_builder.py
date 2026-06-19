"""Argument building for GraphQL field arguments."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, get_type_hints

from graphql.utilities import value_from_ast_untyped
from pydantic import AwareDatetime, TypeAdapter, ValidationError

from nexusx.type_converter import TypeConverter

_DATETIME_ADAPTER = TypeAdapter(AwareDatetime)


class ArgumentBuilder:
    """Builds method arguments from GraphQL field arguments."""

    def __init__(self) -> None:
        """Initialize the argument builder."""
        self._converter = TypeConverter(set())

    def _extract_value(self, node: Any, variables: dict[str, Any] | None = None) -> Any:
        """Extract Python value from a GraphQL AST value node.

        Delegates to graphql-core's ``value_from_ast_untyped``. When
        ``variables`` is provided, variable references (``$foo``) are resolved
        against it; otherwise variable nodes resolve to ``None``.
        """
        return value_from_ast_untyped(node, variables)

    def _is_input_type(self, python_type: type, entity_names: set[str]) -> bool:
        """Check if a type should be treated as a GraphQL Input type."""
        if not isinstance(python_type, type):
            return False
        # Skip if it's an entity type
        if python_type.__name__ in entity_names:
            return False
        try:
            from pydantic import BaseModel
            from sqlmodel import SQLModel
            if issubclass(python_type, SQLModel) or issubclass(python_type, BaseModel):
                return True
        except TypeError:
            pass
        return False

    def _convert_to_input_model(
        self, value: Any, target_type: type, entity_names: set[str]
    ) -> Any:
        """Convert a dict value to an Input model instance if needed."""
        if not isinstance(value, dict):
            return value
        if not self._is_input_type(target_type, entity_names):
            return value

        # Recursively convert nested dict values
        model_fields = getattr(target_type, "model_fields", {})
        converted = {}
        for key, val in value.items():
            if key in model_fields:
                field_info = model_fields[key]
                field_type = field_info.annotation
                converted[key] = self._convert_to_input_model(val, field_type, entity_names)
            else:
                converted[key] = val

        return target_type(**converted)

    def _convert_scalar_value(self, value: Any, target_type: Any) -> Any:
        """Convert GraphQL scalar values that need Python runtime types."""
        if value is None:
            return None

        if self._converter.is_optional(target_type):
            target_type = self._converter.unwrap_optional(target_type)
        if target_type is datetime and isinstance(value, str):
            return self._parse_datetime(value)

        return value

    def _parse_datetime(self, value: str) -> datetime:
        """Parse a timezone-aware DateTime string and normalize it to UTC."""
        try:
            parsed = _DATETIME_ADAPTER.validate_python(value)
        except ValidationError as exc:
            raise ValueError("DateTime values must include timezone information") from exc

        return parsed.astimezone(timezone.utc)

    def build_arguments(
        self,
        selection: Any,
        variables: dict[str, Any] | None,
        method: Any,
        entity: type,
        entity_names: set[str] | None = None,
    ) -> dict[str, Any]:
        """Build method arguments from GraphQL field arguments.

        Args:
            selection: GraphQL FieldNode with argument info.
            variables: GraphQL variables dict.
            method: The method to call.
            entity: The SQLModel entity class.
            entity_names: Set of known entity class names.

        Returns:
            Dictionary of argument name to value.
        """
        args: dict[str, Any] = {}
        variables = variables or {}
        entity_names = entity_names or set()

        if not selection.arguments:
            return args

        # Get method signature and type hints
        func = method.__func__ if hasattr(method, "__func__") else method
        sig = inspect.signature(func)

        try:
            hints = get_type_hints(func)
        except Exception:
            hints = {}

        for arg in selection.arguments:
            arg_name = arg.name.value

            # value_from_ast_untyped resolves variables against the dict directly
            value = self._extract_value(arg.value, variables)

            # Use argument name directly
            param_name = arg_name

            # Determine the actual parameter name
            actual_param_name = None
            if param_name in sig.parameters:
                actual_param_name = param_name
            elif arg_name in sig.parameters:
                actual_param_name = arg_name

            if actual_param_name:
                # Convert to Input model if the parameter type is an Input type
                if actual_param_name in hints:
                    param_type = hints[actual_param_name]
                    value = self._convert_scalar_value(value, param_type)
                    value = self._convert_to_input_model(value, param_type, entity_names)
                args[actual_param_name] = value

        return args
