"""Schema formatter for MCP tools.

Formats GraphQL introspection data into a simplified structure for AI consumption.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nexusx.handler import GraphQLHandler


class SchemaFormatter:
    """Formats GraphQL schema information for MCP tools.

    Takes the full introspection data from IntrospectionGenerator and
    extracts a simplified, AI-friendly structure.
    """

    def __init__(self, handler: GraphQLHandler):
        """Initialize the schema formatter.

        Args:
            handler: The GraphQLHandler instance to extract schema from.
        """
        self._handler = handler
        self._introspection = handler.get_introspection_data()

    def get_schema_info(self) -> dict[str, Any]:
        """Get formatted schema information.

        Returns:
            Dictionary containing:
            - queries: List of available query operations
            - mutations: List of available mutation operations
            - types: List of entity types with their fields
            - input_types: List of input types with their fields
        """
        return {
            "queries": self._get_queries(),
            "mutations": self._get_mutations(),
            "types": self._get_types(),
            "input_types": self._get_input_types(),
        }

    def _get_queries(self) -> list[dict[str, Any]]:
        """Extract query operations from schema."""
        queries: list[dict[str, Any]] = []

        # Find Query type in introspection data
        for type_info in self._introspection.get("types", []):
            if type_info.get("name") == "Query":
                for field in type_info.get("fields", []):
                    queries.append(self._format_field(field))
                break

        return queries

    def _get_mutations(self) -> list[dict[str, Any]]:
        """Extract mutation operations from schema."""
        mutations: list[dict[ str, Any]] = []

        # Find Mutation type in introspection data
        for type_info in self._introspection.get("types", []):
            if type_info.get("name") == "Mutation":
                for field in type_info.get("fields", []):
                    mutations.append(self._format_field(field))
                break

        return mutations

    def _get_types(self) -> list[dict[str, Any]]:
        """Extract entity types from schema."""
        types: list[dict[str, Any]] = []

        # Get entity names from handler
        entity_names = {e.__name__ for e in self._handler.entities}

        for type_info in self._introspection.get("types", []):
            type_name = type_info.get("name", "")
            # Only include entity types (not Query, Mutation, or built-in scalars)
            if type_name in entity_names:
                types.append(self._format_type(type_info))

        return types

    def _get_input_types(self) -> list[dict[str, Any]]:
        """Extract input types from schema."""
        input_types: list[dict[str, Any]] = []

        for type_info in self._introspection.get("types", []):
            if type_info.get("kind") == "INPUT_OBJECT":
                input_types.append(self._format_input_type(type_info))

        return input_types

    def _format_input_type(self, type_info: dict[str, Any]) -> dict[str, Any]:
        """Format an input type for AI consumption.

        Args:
            type_info: The introspection type data.

        Returns:
            Simplified input type dictionary.
        """
        input_fields = type_info.get("inputFields", [])

        fields = [
            {
                "name": field.get("name"),
                "type": self._simplify_type_ref(field.get("type")),
                "required": self._is_required(field.get("type")),
                "description": field.get("description"),
            }
            for field in input_fields
        ]

        return {
            "name": type_info.get("name"),
            "description": type_info.get("description"),
            "fields": fields,
        }

    def _format_field(self, field: dict[str, Any]) -> dict[str, Any]:
        """Format a field (query/mutation) for AI consumption.

        Args:
            field: The introspection field data.

        Returns:
            Simplified field dictionary.
        """
        return {
            "name": field.get("name"),
            "description": field.get("description"),
            "arguments": [
                {
                    "name": arg.get("name"),
                    "type": self._simplify_type_ref(arg.get("type")),
                    "required": self._is_required(arg.get("type")),
                    "default_value": arg.get("defaultValue"),
                }
                for arg in field.get("args", [])
            ],
            "return_type": self._simplify_type_ref(field.get("type")),
        }

    def _format_type(self, type_info: dict[str, Any]) -> dict[str, Any]:
        """Format an entity type for AI consumption.

        Args:
            type_info: The introspection type data.

        Returns:
            Simplified type dictionary.
        """
        fields = type_info.get("fields", [])

        # Separate scalar fields from relationship fields
        scalar_fields: list[dict[str, Any]] = []
        relationship_fields: list[dict[str, Any]] = []

        for field in fields:
            field_info = {
                "name": field.get("name"),
                "type": self._simplify_type_ref(field.get("type")),
                "required": self._is_required(field.get("type")),
                "description": field.get("description"),
            }

            if self._is_relationship_type(field.get("type")):
                relationship_fields.append(field_info)
            else:
                scalar_fields.append(field_info)

        return {
            "name": type_info.get("name"),
            "description": type_info.get("description"),
            "scalar_fields": scalar_fields,
            "relationship_fields": relationship_fields,
        }

    def _simplify_type_ref(self, type_ref: dict[str, Any] | None) -> str:
        """Simplify a GraphQL type reference to a readable string.

        Args:
            type_ref: The introspection type reference.

        Returns:
            Human-readable type string (e.g., "[User]!", "String", "Int").
        """
        if type_ref is None:
            return "Unknown"

        kind = type_ref.get("kind")
        name = type_ref.get("name")
        of_type = type_ref.get("ofType")

        if kind == "NON_NULL":
            inner = self._simplify_type_ref(of_type)
            return f"{inner}!"
        if kind == "LIST":
            inner = self._simplify_type_ref(of_type)
            return f"[{inner}]"
        if name:
            return name

        return "Unknown"

    def _is_required(self, type_ref: dict[str, Any] | None) -> bool:
        """Check if a type reference is non-null (required).

        Args:
            type_ref: The introspection type reference.

        Returns:
            True if the type is required.
        """
        if type_ref is None:
            return False
        return type_ref.get("kind") == "NON_NULL"

    def _is_relationship_type(self, type_ref: dict[str, Any] | None) -> bool:
        """Check if a type reference represents a relationship to another entity.

        Args:
            type_ref: The introspection type reference.

        Returns:
            True if the type is a relationship to an entity.
        """
        if type_ref is None:
            return False

        kind = type_ref.get("kind")
        name = type_ref.get("name")
        of_type = type_ref.get("ofType")

        # Direct entity type
        if kind == "OBJECT" and name:
            return self._is_entity_name(name)

        # Non-null wrapper
        if kind == "NON_NULL":
            return self._is_relationship_type(of_type)

        # List wrapper
        if kind == "LIST":
            return self._is_relationship_type(of_type)

        return False

    def _is_entity_name(self, name: str) -> bool:
        """Check if a name refers to a known entity type.

        Args:
            name: The type name to check.

        Returns:
            True if the name is an entity type.
        """
        entity_names = {e.__name__ for e in self._handler.entities}
        return name in entity_names
