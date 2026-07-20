"""Type tracer for collecting related GraphQL types.

This module provides functionality to trace and collect all entity types
that are related to a specific GraphQL operation (query or mutation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class TypeTracer:
    """Traces and collects all entity types related to a GraphQL operation.

    This class analyzes GraphQL introspection data to find all entity types
    that are reachable from a given operation's return type. It handles
    circular references by tracking visited types.

    Example:
        >>> tracer = TypeTracer(introspection_data, {"User", "Post"})
        >>> types = tracer.collect_related_types(return_type_ref)
        >>> # types might be {"User", "Post"} if User has posts field
        >>> introspection = tracer.get_introspection_for_types(types)
    """

    def __init__(self, introspection_data: dict[str, Any], entity_names: set[str]):
        """Initialize the type tracer.

        Args:
            introspection_data: Full GraphQL introspection data containing all types.
            entity_names: Set of entity type names to consider when tracing.
        """
        self._introspection = introspection_data
        self._entity_names = entity_names
        self._type_cache: dict[str, dict[str, Any]] = {}
        self._build_type_cache()

    def _build_type_cache(self) -> None:
        """Build a cache of type name to type info for quick lookup."""
        for type_info in self._introspection.get("types", []):
            name = type_info.get("name")
            if name:
                self._type_cache[name] = type_info

    def _get_type_info(self, name: str) -> dict[str, Any] | None:
        """Get type info by name from cache.

        Args:
            name: The type name to look up.

        Returns:
            Type info dictionary or None if not found.
        """
        return self._type_cache.get(name)

    def collect_related_types(self, type_ref: dict[str, Any] | None) -> set[str]:
        """Collect all entity types reachable from the given type reference.

        This method recursively traces through type references to find all
        entity types that are reachable. It handles LIST and NON_NULL wrappers
        and follows relationship fields to discover nested entity types.

        Args:
            type_ref: A GraphQL type reference from introspection data.

        Returns:
            Set of entity type names that are reachable from the given type.
        """
        if type_ref is None:
            return set()

        visited: set[str] = set()

        def trace(ref: dict[str, Any] | None) -> None:
            if ref is None:
                return

            kind = ref.get("kind")
            name = ref.get("name")
            of_type = ref.get("ofType")

            if kind == "OBJECT" and name in self._entity_names:
                if name not in visited:
                    visited.add(name)
                    # Recursively trace fields of this type
                    type_info = self._get_type_info(name)
                    if type_info:
                        for field in type_info.get("fields", []):
                            trace(field.get("type"))

            elif kind == "LIST":
                trace(of_type)

            elif kind == "NON_NULL":
                trace(of_type)

        trace(type_ref)
        return visited

    def get_introspection_for_types(self, type_names: set[str]) -> list[dict[str, Any]]:
        """Get introspection data for the specified type names.

        Args:
            type_names: Set of type names to get introspection data for.

        Returns:
            List of type introspection dictionaries.
        """
        result: list[dict[str, Any]] = []
        for name in sorted(type_names):  # Sort for consistent ordering
            type_info = self._get_type_info(name)
            if type_info:
                result.append(type_info)
        return result

    def get_operation_field(
        self, operation_type: str, field_name: str
    ) -> dict[str, Any] | None:
        """Get a specific field from Query or Mutation type.

        Args:
            operation_type: Either "Query" or "Mutation".
            field_name: The name of the field to get.

        Returns:
            Field introspection data or None if not found.
        """
        type_info = self._get_type_info(operation_type)
        if not type_info:
            return None

        for field in type_info.get("fields", []):
            if field.get("name") == field_name:
                return field

        return None

    def list_operation_fields(
        self, operation_type: str
    ) -> list[dict[str, str | None]]:
        """List all fields (operations) for Query or Mutation type.

        Args:
            operation_type: Either "Query" or "Mutation".

        Returns:
            List of dictionaries with name and description for each field.

        Note:
            Under the grouped layout the root Query/Mutation fields are entity
            groups (``User: UserQuery!``), not individual operations. To list
            the actual methods use :meth:`list_group_operations`.
        """
        type_info = self._get_type_info(operation_type)
        if not type_info:
            return []

        result: list[dict[str, str | None]] = []
        for field in type_info.get("fields", []):
            result.append({
                "name": field.get("name"),
                "description": field.get("description"),
            })

        return result

    @staticmethod
    def _unwrap_type_name(type_ref: dict[str, Any] | None) -> str | None:
        """Unwrap a GraphQL type ref (NON_NULL/LIST) to its named type."""
        ref = type_ref
        while ref is not None:
            name = ref.get("name")
            if name:
                return name
            ref = ref.get("ofType")
        return None

    def list_group_operations(
        self, operation_type: str
    ) -> list[dict[str, Any]]:
        """List all methods across every entity group for Query or Mutation.

        Under the grouped layout the root ``Query``/``Mutation`` fields are
        entity groups (``User: UserQuery!``); the actual operations are the
        method fields on the ``{Entity}Query``/``{Entity}Mutation`` types.
        This descends into each group and returns one entry per method.

        Returns:
            One dict per method: ``{entity, method, name ("<entity>.<method>"),
            description}``.
        """
        type_info = self._get_type_info(operation_type)
        if not type_info:
            return []

        result: list[dict[str, Any]] = []
        for group_field in type_info.get("fields", []):
            entity_name = group_field.get("name")
            group_type_name = self._unwrap_type_name(group_field.get("type"))
            if not group_type_name:
                continue
            group_type = self._get_type_info(group_type_name)
            if not group_type:
                continue
            for method_field in group_type.get("fields", []):
                method_name = method_field.get("name")
                result.append({
                    "entity": entity_name,
                    "method": method_name,
                    "name": f"{entity_name}.{method_name}",
                    "description": method_field.get("description"),
                })
        return result

    def get_group_operation(
        self, operation_type: str, entity_name: str, method_name: str
    ) -> dict[str, Any] | None:
        """Get a method field from its ``{Entity}Query``/``{Entity}Mutation`` group.

        Args:
            operation_type: "Query" or "Mutation".
            entity_name: Entity class name (the group field on the root type).
            method_name: Method name verbatim.

        Returns:
            The method field introspection dict, or None if not found.
        """
        root_field = self.get_operation_field(operation_type, entity_name)
        if not root_field:
            return None
        group_type_name = self._unwrap_type_name(root_field.get("type"))
        if not group_type_name:
            return None
        group_type = self._get_type_info(group_type_name)
        if not group_type:
            return None
        for field in group_type.get("fields", []):
            if field.get("name") == method_name:
                return field
        return None
