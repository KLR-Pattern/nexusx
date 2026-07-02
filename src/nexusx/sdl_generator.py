"""GraphQL SDL generator for SQLModel classes."""

from __future__ import annotations

import inspect
import logging
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints

from sqlmodel import SQLModel

from nexusx.introspection import QUERY_META_PARAM  # noqa: F401
from nexusx.type_converter import TypeConverter
from nexusx.utils.naming import to_graphql_field_name
from nexusx.utils.schema_helpers import get_core_types, is_input_type

logger = logging.getLogger(__name__)


def _python_type_to_graphql(
    python_type: Any, converter: TypeConverter, entity_names: set[str] | None = None
) -> str:
    """Convert Python type to GraphQL type string."""
    origin = get_origin(python_type)

    # Handle list types
    if origin is list:
        args = get_args(python_type)
        if args:
            inner = args[0]
            is_element_nullable = converter.is_optional(inner)
            if is_element_nullable:
                inner = converter.unwrap_optional(inner)
            inner_type = _python_type_to_graphql_inner(
                inner, converter, nullable=is_element_nullable, entity_names=entity_names
            )
            return f"[{inner_type}]!"
        return "[String!]!"

    # Handle Optional
    if converter.is_optional(python_type):
        inner = converter.unwrap_optional(python_type)
        result = _python_type_to_graphql(inner, converter, entity_names=entity_names)
        # Strip trailing '!' if present — Optional means nullable
        if result.endswith("!"):
            result = result[:-1]
        return result

    # Non-nullable type
    return _python_type_to_graphql_inner(
        python_type, converter, nullable=False, entity_names=entity_names
    )


def _python_type_to_graphql_inner(
    python_type: Any,
    converter: TypeConverter,
    nullable: bool = True,
    entity_names: set[str] | None = None,
) -> str:
    """Convert Python type to GraphQL type string (inner, without list wrapper)."""
    # Handle enum types
    if converter.is_enum_type(python_type):
        return python_type.__name__

    # Check if it's an entity type
    entity_name = converter.get_entity_name(python_type)
    if entity_name:
        return f"{entity_name}{'!' if not nullable else ''}"

    # Check if it's an Input type (SQLModel or BaseModel not in entities)
    is_input = (
        entity_names is not None
        and is_input_type(python_type)
        and python_type.__name__ not in entity_names
    )
    if is_input:
        return f"{python_type.__name__}{'!' if not nullable else ''}"

    # Handle basic Python types
    base_type = converter.get_scalar_type_name(python_type) or "String"
    return f"{base_type}{'!' if not nullable else ''}"


class SDLGenerator:
    """Generates GraphQL SDL from SQLModel classes."""

    def __init__(
        self,
        entities: list[type[SQLModel]],
        query_description: str | None = None,
        mutation_description: str | None = None,
    ):
        """Initialize the SDL generator.

        Args:
            entities: List of SQLModel classes to generate schema for.
            query_description: Optional custom description for Query type.
            mutation_description: Optional custom description for Mutation type.
        """
        self.entities = entities
        self._entity_names = {e.__name__ for e in entities}
        self._entity_map = {e.__name__: e for e in entities}
        self._converter = TypeConverter(self._entity_names)
        self._query_description = query_description
        self._mutation_description = mutation_description
        self._enable_pagination = False
        self._loader_registry: Any = None

    def generate(
        self,
        include_mutations: bool = True,
        enable_pagination: bool = False,
        loader_registry: Any | None = None,
    ) -> str:
        """Generate complete GraphQL SDL string.

        Args:
            include_mutations: If True, includes Mutation type in SDL. Default is True.
            enable_pagination: If True, list relationship fields become Result types.
            loader_registry: ErManager for relationship introspection (required
                when enable_pagination is True).
        """
        self._enable_pagination = enable_pagination
        self._loader_registry = loader_registry

        parts = []

        # 1. Generate enum types
        enum_defs = self._generate_enums()
        parts.extend(enum_defs)

        # 2. Collect and generate Input types
        input_types = self._collect_input_types()
        for input_type in sorted(input_types, key=lambda t: t.__name__):
            parts.append(self._generate_input_type(input_type))

        # 3. Generate entity types
        for entity in self.entities:
            parts.append(self._generate_type(entity))

        # 4. Generate Pagination and Result types (if pagination enabled)
        if enable_pagination:
            pag_types = self._generate_pagination_types()
            if pag_types:
                parts.append(pag_types)

        # 5. Generate Query type
        query_fields = self._collect_query_fields()
        if query_fields:
            query_def = f"type Query {{\n{chr(10).join(query_fields)}\n}}"
            if self._query_description:
                query_def = f'"""{self._query_description}"""\n{query_def}'
            parts.append(query_def)

        # 6. Generate Mutation type (conditional)
        if include_mutations:
            mutation_fields = self._collect_mutation_fields()
            if mutation_fields:
                mutation_def = f"type Mutation {{\n{chr(10).join(mutation_fields)}\n}}"
                if self._mutation_description:
                    mutation_def = f'"""{self._mutation_description}"""\n{mutation_def}'
                parts.append(mutation_def)

        return "\n\n".join(parts)

    def _generate_enums(self) -> list[str]:
        """Generate GraphQL enum types from Python enums used in entities."""
        enums: dict[str, type[Enum]] = {}

        for entity in self.entities:
            hints = get_type_hints(entity)
            for field_type in hints.values():
                if isinstance(field_type, type) and issubclass(field_type, Enum):
                    enums[field_type.__name__] = field_type

        result = []
        for enum_name, enum_class in enums.items():
            values = "\n".join(f"  {v.value}" for v in enum_class)
            result.append(f"enum {enum_name} {{\n{values}\n}}")

        return result

    def _collect_input_types(self) -> set[type]:
        """Collect all Input types from query and mutation parameters.

        Input types are SQLModel or BaseModel subclasses that are NOT in the entity list.
        They are used as parameters in query/mutation methods.
        """
        input_types: set[type] = set()
        visited: set[str] = set()

        def collect_from_type(param_type: Any) -> None:
            """Recursively collect Input types from a type hint."""
            core_types = get_core_types(param_type)

            for core_type in core_types:
                if is_input_type(core_type) and core_type.__name__ not in self._entity_names:
                    type_name = core_type.__name__
                    if type_name not in visited:
                        visited.add(type_name)
                        input_types.add(core_type)

                        # Recursively collect nested types
                        try:
                            type_hints = get_type_hints(core_type)
                            for field_type in type_hints.values():
                                collect_from_type(field_type)
                        except (NameError, AttributeError):
                            pass

        # Scan all query and mutation methods
        for entity in self.entities:
            for name in dir(entity):
                try:
                    attr = getattr(entity, name)
                    if not callable(attr):
                        continue
                    func = attr.__func__ if hasattr(attr, "__func__") else attr

                    # Check if method has a pre-defined filter input type
                    if hasattr(func, "_filter_input_type"):
                        filter_input_type = func._filter_input_type
                        type_name = filter_input_type.__name__
                        if type_name not in visited:
                            visited.add(type_name)
                            input_types.add(filter_input_type)
                            try:
                                type_hints = get_type_hints(filter_input_type)
                                for field_type in type_hints.values():
                                    collect_from_type(field_type)
                            except (NameError, AttributeError):
                                pass

                    # Check for @query or @mutation
                    if hasattr(func, "_graphql_query") or hasattr(func, "_graphql_mutation"):
                        sig = inspect.signature(func)
                        try:
                            globalns = getattr(func, "__globals__", {})
                            localns = {e.__name__: e for e in self.entities}
                            hints = get_type_hints(func, globalns=globalns, localns=localns)
                        except (NameError, AttributeError):
                            hints = {}

                        for param_name, _param in sig.parameters.items():
                            if param_name in ("cls", "self", QUERY_META_PARAM):
                                continue
                            if param_name in hints:
                                collect_from_type(hints[param_name])
                except (AttributeError, NameError):
                    continue
                except Exception:
                    logger.warning(
                        "Unexpected error scanning %s.%s",
                        entity.__name__, name, exc_info=True,
                    )
                    continue

        return input_types

    def _generate_input_type(self, input_type: type) -> str:
        """Generate GraphQL input type definition from a SQLModel or BaseModel class."""
        fields: list[str] = []

        # Get model_fields if available (SQLModel/Pydantic)
        model_fields = getattr(input_type, "model_fields", {})

        # Only use model_fields, not type hints (to avoid SQLModel internal fields like 'metadata')
        for field_name, field_info in model_fields.items():
            if field_name.startswith("_"):
                continue

            # Skip SQLModel internal fields
            if field_name == "metadata":
                continue

            # Get the annotation from field_info
            field_type = field_info.annotation

            # Convert type to GraphQL
            gql_type = self._input_type_to_graphql(field_type, field_info)

            # Add field description if available
            if field_info and getattr(field_info, "description", None):
                fields.append(f'  """{field_info.description}"""')

            fields.append(f"  {field_name}: {gql_type}")

        # Build input type definition with optional description
        type_def = f"input {input_type.__name__} {{\n{chr(10).join(fields)}\n}}"
        if input_type.__doc__:
            type_def = f'"""{input_type.__doc__}"""\n{type_def}'
        return type_def

    def _input_type_to_graphql(
        self,
        python_type: Any,
        field_info: Any = None,
        is_optional: bool = False,
    ) -> str:
        """Convert Python type to GraphQL type string for Input types."""
        origin = get_origin(python_type)

        # Handle list types
        if origin is list:
            args = get_args(python_type)
            if args:
                inner = args[0]
                is_element_nullable = self._converter.is_optional(inner)
                inner_type = self._input_type_to_graphql(inner, is_optional=is_element_nullable)
                return f"[{inner_type}]!"
            return "[String!]!"

        # Handle Optional
        if self._converter.is_optional(python_type):
            inner = self._converter.unwrap_optional(python_type)
            # Don't add ! for optional types
            return self._input_type_to_graphql(inner, is_optional=True)

        # Handle enum types
        if self._converter.is_enum_type(python_type):
            return python_type.__name__

        # Check if it's another Input type (SQLModel or BaseModel not in entities)
        if is_input_type(python_type) and python_type.__name__ not in self._entity_names:
            return f"{python_type.__name__}" if is_optional else f"{python_type.__name__}!"

        # Check if it's an entity type
        entity_name = self._converter.get_entity_name(python_type)
        if entity_name:
            return entity_name if is_optional else f"{entity_name}!"

        # Handle basic Python types
        base_type = self._converter.get_scalar_type_name(python_type) or "String"
        return base_type if is_optional else f"{base_type}!"

    def _generate_type(self, entity: type[SQLModel]) -> str:
        """Generate GraphQL type definition from SQLModel class."""
        fields: list[str] = []

        # Get scalar fields from model_fields
        for field_name, field_info in entity.model_fields.items():
            # Skip FK fields from output
            if self._is_fk_field(field_info):
                continue
            gql_type = self._field_info_to_graphql(field_info)
            # Add field description if available
            if field_info.description:
                fields.append(f'  """{field_info.description}"""')
            fields.append(f"  {field_name}: {gql_type}")

        # Get relationship fields from type hints
        hints = get_type_hints(entity)
        for field_name, hint in hints.items():
            if field_name in entity.model_fields:
                continue  # Already processed

            # Check if it's a relationship (references another entity)
            gql_type = self._type_hint_to_graphql(hint, entity, field_name)
            if gql_type:
                # Paginated list fields declare limit/offset args to match
                # the introspection path — without them, SDL-only clients
                # cannot tell the field is paginated.
                if self._is_paginated_relationship(entity, field_name):
                    fields.append(
                        f"  {field_name}(limit: Int, offset: Int = 0): {gql_type}"
                    )
                else:
                    fields.append(f"  {field_name}: {gql_type}")

        # Build type definition with optional description
        type_def = f"type {entity.__name__} {{\n{chr(10).join(fields)}\n}}"
        if entity.__doc__:
            type_def = f'"""{entity.__doc__}"""\n{type_def}'
        return type_def

    def _is_fk_field(self, field_info: Any) -> bool:
        """Check if a field is a foreign key field (should be excluded from GraphQL output)."""
        if hasattr(field_info, "foreign_key") and isinstance(field_info.foreign_key, str):
            return True
        if hasattr(field_info, "metadata"):
            for meta in field_info.metadata:
                if hasattr(meta, "foreign_key") and isinstance(meta.foreign_key, str):
                    return True
        return False

    def _type_hint_to_graphql(
        self, hint: Any, entity: type[SQLModel] | None = None, field_name: str | None = None
    ) -> str | None:
        """Convert type hint to GraphQL type if it's an entity reference."""
        # Unwrap Mapped wrapper if present
        if self._converter.is_mapped_wrapper(hint):
            hint = self._converter.unwrap_mapped(hint)

        origin = get_origin(hint)

        # Handle list of entities
        if origin is list:
            inner = self._converter.get_list_inner_type(hint)
            entity_name = self._converter.get_entity_name(inner)
            if entity_name:
                # Check if pagination is enabled for this relationship
                if (
                    self._enable_pagination
                    and entity
                    and field_name
                    and self._is_paginated_relationship(entity, field_name)
                ):
                    return f"{entity_name}Result!"
                return f"[{entity_name}!]!"
            return None

        # Handle Optional entity (e.g., Optional[User])
        if self._converter.is_optional(hint):
            inner = self._converter.unwrap_optional(hint)
            entity_name = self._converter.get_entity_name(inner)
            if entity_name:
                return entity_name  # Optional, no !
            return None

        # Handle single entity
        entity_name = self._converter.get_entity_name(hint)
        if entity_name:
            return f"{entity_name}!"

        return None

    def _is_paginated_relationship(
        self, entity: type[SQLModel], field_name: str
    ) -> bool:
        """Check if a relationship has pagination enabled (page_loader configured)."""
        if not self._loader_registry:
            return False
        rel_info = self._loader_registry.get_relationship(entity, field_name)
        return rel_info is not None and rel_info.page_loader is not None

    def _generate_pagination_types(self) -> str | None:
        """Generate Pagination type and Result types for paginated relationships."""
        if not self._loader_registry:
            return None

        result_type_names: set[str] = set()
        parts: list[str] = []

        # Pagination base type
        parts.append(
            "type Pagination {\n"
            "  has_more: Boolean!\n"
            "  total_count: Int\n"
            "}"
        )

        # Generate Result types for each paginated relationship
        for entity in self.entities:
            rels = self._loader_registry.get_relationships(entity)
            for _rel_name, rel_info in rels.items():
                if rel_info.is_list and rel_info.page_loader is not None:
                    target_name = rel_info.target_entity.__name__
                    result_type_name = f"{target_name}Result"
                    if result_type_name not in result_type_names:
                        result_type_names.add(result_type_name)
                        parts.append(
                            f"type {result_type_name} {{\n"
                            f"  items: [{target_name}!]!\n"
                            f"  pagination: Pagination!\n"
                            f"}}",
                        )

        return "\n\n".join(parts) if parts else None

    def _field_info_to_graphql(self, field_info: Any) -> str:
        """Convert Pydantic FieldInfo to GraphQL type."""
        annotation = field_info.annotation
        return _python_type_to_graphql(annotation, self._converter)

    def _collect_query_fields(self) -> list[str]:
        """Collect @query methods from all entities."""
        fields: list[str] = []

        for entity in self.entities:
            for name in dir(entity):
                try:
                    attr = getattr(entity, name)
                    if not callable(attr):
                        continue
                    # Check for _graphql_query on the function (classmethod wraps it)
                    func = attr.__func__ if hasattr(attr, "__func__") else attr
                    if hasattr(func, "_graphql_query"):
                        field_def = self._method_to_graphql_field(attr, entity)
                        fields.append(f"  {field_def}")
                except (AttributeError, NameError):
                    continue
                except Exception:
                    logger.warning(
                        "Unexpected error collecting query from %s.%s",
                        entity.__name__, name, exc_info=True,
                    )
                    continue

        return fields

    def _collect_mutation_fields(self) -> list[str]:
        """Collect @mutation methods from all entities."""
        fields: list[str] = []

        for entity in self.entities:
            for name in dir(entity):
                try:
                    attr = getattr(entity, name)
                    if not callable(attr):
                        continue
                    # Check for _graphql_mutation on the function (classmethod wraps it)
                    func = attr.__func__ if hasattr(attr, "__func__") else attr
                    if hasattr(func, "_graphql_mutation"):
                        field_def = self._method_to_graphql_field(attr, entity)
                        fields.append(f"  {field_def}")
                except (AttributeError, NameError):
                    continue
                except Exception:
                    logger.warning(
                        "Unexpected error collecting mutation from %s.%s",
                        entity.__name__, name, exc_info=True,
                    )
                    continue

        return fields

    def _method_to_graphql_field(self, method: Any, entity: type[SQLModel]) -> str:
        """Convert a method to GraphQL field definition."""
        # Get the underlying function from classmethod
        func = method.__func__ if hasattr(method, "__func__") else method

        # Generate GraphQL field name: entityName + MethodName
        gql_name = to_graphql_field_name(entity.__name__, func.__name__)

        # Get description from docstring
        description = func.__doc__

        # Get type hints from the function's module context
        # Include entity in localns to resolve forward references
        try:
            globalns = getattr(func, "__globals__", {})
            localns = {entity.__name__: entity}
            # Add all known entities to localns for forward reference resolution
            for e in self.entities:
                localns[e.__name__] = e
            hints = get_type_hints(func, globalns=globalns, localns=localns)
        except (NameError, AttributeError):
            hints = {}

        # Parse method signature
        sig = inspect.signature(func)
        params: list[str] = []

        for param_name, _param in sig.parameters.items():
            if param_name in ("cls", "self", QUERY_META_PARAM):
                continue

            if param_name == "filter":
                # Check if method has a pre-defined filter input type
                if hasattr(func, "_filter_input_type"):
                    filter_input_type = func._filter_input_type
                else:
                    filter_input_type = None

                if filter_input_type:
                    gql_type = f"{filter_input_type.__name__}"
                    params.append(f"{param_name}: {gql_type}")
                elif param_name in hints:
                    gql_type = _python_type_to_graphql(
                        hints[param_name], self._converter, self._entity_names
                    )
                    if _param.default != inspect.Parameter.empty:
                        gql_type = gql_type.rstrip("!")
                    params.append(f"{param_name}: {gql_type}")
                else:
                    params.append(f"{param_name}: String!")
            elif param_name in hints:
                gql_type = _python_type_to_graphql(
                    hints[param_name], self._converter, self._entity_names
                )
                if _param.default != inspect.Parameter.empty:
                    gql_type = gql_type.rstrip("!")
                params.append(f"{param_name}: {gql_type}")
            else:
                params.append(f"{param_name}: String!")

        # Get return type
        return_type = hints.get("return", inspect.Signature.empty)
        if return_type != inspect.Signature.empty:
            return_gql_type = _python_type_to_graphql(
                return_type, self._converter, self._entity_names
            )
        else:
            return_gql_type = "String!"

        # Build field definition
        param_str = f"({', '.join(params)})" if params else ""
        field_def = f"{gql_name}{param_str}: {return_gql_type}"

        if description:
            field_def = f'"""{description}"""\n  {field_def}'

        return field_def

    def _collect_related_entities(
        self, type_hint: Any, visited: set[str] | None = None
    ) -> set[str]:
        """Recursively collect all entity types related to a type hint.

        Args:
            type_hint: Python type hint to analyze.
            visited: Set of already visited entity names (for cycle detection).

        Returns:
            Set of entity names that are reachable from the type hint.
        """
        if visited is None:
            visited = set()

        # Unwrap type to get base type
        base_type = self._converter.unwrap_to_base_type(type_hint)

        # Check if it's an entity
        entity_name = self._converter.get_entity_name(base_type)
        if not entity_name or entity_name in visited:
            return visited

        visited.add(entity_name)

        # Get the entity class
        entity = self._entity_map.get(entity_name)
        if not entity:
            return visited

        # Recursively collect from entity's fields
        hints = get_type_hints(entity)
        for field_hint in hints.values():
            visited = self._collect_related_entities(field_hint, visited)

        return visited

    def _find_operation_method(
        self, operation_name: str, operation_type: str
    ) -> tuple[Any, type[SQLModel]] | None:
        """Find the method and entity for a given operation name.

        Args:
            operation_name: Name of the GraphQL operation (e.g., "userGetAll").
            operation_type: "Query" or "Mutation".

        Returns:
            Tuple of (method, entity) or None if not found.
        """
        decorator_attr = (
            "_graphql_query" if operation_type == "Query" else "_graphql_mutation"
        )

        for entity in self.entities:
            for name in dir(entity):
                try:
                    attr = getattr(entity, name)
                    if callable(attr) and hasattr(attr, decorator_attr):
                        func = attr.__func__ if hasattr(attr, "__func__") else attr
                        # Generate GraphQL field name and compare
                        gql_name = to_graphql_field_name(entity.__name__, func.__name__)
                        if gql_name == operation_name:
                            return (attr, entity)
                except (AttributeError, NameError):
                    continue

        return None

    def generate_operation_sdl(
        self, operation_name: str, operation_type: str = "Query"
    ) -> str | None:
        """Generate SDL for a single operation and its related types.

        Args:
            operation_name: Name of the GraphQL operation (e.g., "users").
            operation_type: "Query" or "Mutation".

        Returns:
            SDL string for the operation and related types, or None if not found.

        Example:
            >>> generator.generate_operation_sdl("users", "Query")
            '# Query\\nusers(limit: Int): [User!]!\\n\\n# Related Types\\ntype User { ... }'
        """
        # Find the operation method
        result = self._find_operation_method(operation_name, operation_type)
        if not result:
            return None

        method, entity = result

        # Get return type to collect related entities
        func = method.__func__ if hasattr(method, "__func__") else method
        try:
            globalns = getattr(func, "__globals__", {})
            localns = {e.__name__: e for e in self.entities}
            hints = get_type_hints(func, globalns=globalns, localns=localns)
            return_type = hints.get("return")
        except (NameError, AttributeError):
            return_type = None

        # Collect related entity names
        related_entities: set[str] = set()
        if return_type:
            related_entities = self._collect_related_entities(return_type)

        # For mutations, also collect from argument types
        if operation_type == "Mutation":
            sig = inspect.signature(func)
            for param_name in sig.parameters:
                if param_name in ("cls", "self", QUERY_META_PARAM):
                    continue
                if param_name in hints:
                    related_entities.update(self._collect_related_entities(hints[param_name]))

        # Build SDL parts
        parts = []

        # Generate operation line
        field_def = self._method_to_graphql_field(method, entity)
        # Remove leading spaces from field_def (it's formatted for type body)
        field_def = field_def.strip()
        parts.append(f"# {operation_type}\n{field_def}")

        # Generate related types
        if related_entities:
            type_parts = []
            for entity_name in sorted(related_entities):
                related_entity = self._entity_map.get(entity_name)
                if related_entity:
                    type_parts.append(self._generate_type(related_entity))
            if type_parts:
                parts.append("# Related Types\n" + "\n\n".join(type_parts))

        return "\n\n".join(parts)
