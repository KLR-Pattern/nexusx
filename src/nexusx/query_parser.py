"""GraphQL query parser for extracting selection trees and arguments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graphql import DocumentNode, FieldNode, OperationDefinitionNode, parse


@dataclass
class FieldSelection:
    """Represents a selected field with its nested selections and arguments.

    Attributes:
        name: The field name as defined in the SQLModel.
        alias: Optional GraphQL alias for the field.
        arguments: Dict of argument name -> value from GraphQL query.
        sub_fields: Dict of child field name -> FieldSelection for nested selections.
    """

    name: str = ""
    alias: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    sub_fields: dict[str, FieldSelection] = field(default_factory=dict)


class QueryParser:
    """Parses GraphQL queries to extract field selections and arguments."""

    def __init__(self, entity_field_names: set[str] | None = None):
        """Initialize the parser.

        Args:
            entity_field_names: Set of field names that represent entity types
                               (used to distinguish relationships from scalar fields).
        """
        self.entity_field_names = entity_field_names or set()

    def parse(self, query: str) -> dict[str, FieldSelection]:
        """Parse a GraphQL query and return FieldSelection for each operation.

        Args:
            query: GraphQL query string.

        Returns:
            Dictionary mapping operation name to FieldSelection.
        """
        return self.parse_document(parse(query))

    def parse_document(self, document: DocumentNode) -> dict[str, FieldSelection]:
        """Extract FieldSelection tree from an already-parsed DocumentNode.

        Use this when the caller has already parsed the query string (e.g. to
        share the AST with the executor) to avoid a second ``parse()`` pass.
        """
        result: dict[str, FieldSelection] = {}

        for definition in document.definitions:
            if isinstance(definition, OperationDefinitionNode):
                for selection in definition.selection_set.selections:
                    if isinstance(selection, FieldNode):
                        operation_name = selection.name.value
                        if selection.selection_set:
                            meta = self._parse_selection_set(selection.selection_set)
                            result[operation_name] = meta

        return result

    def validate_no_aliases(self, query: str) -> None:
        """Reject GraphQL aliases explicitly."""
        document = parse(query)

        for definition in document.definitions:
            if isinstance(definition, OperationDefinitionNode):
                self._validate_selection_set_no_aliases(definition.selection_set)

    def _validate_selection_set_no_aliases(self, selection_set: Any) -> None:
        """Recursively validate that a selection set contains no aliases."""
        for selection in selection_set.selections:
            alias = getattr(selection, "alias", None)
            if alias is not None:
                raise ValueError("GraphQL aliases are not supported")

            nested_selection_set = getattr(selection, "selection_set", None)
            if nested_selection_set is not None:
                self._validate_selection_set_no_aliases(nested_selection_set)

    def _parse_selection_set(self, selection_set: Any) -> FieldSelection:
        """Internal method to parse selection set into FieldSelection."""
        sub_fields: dict[str, FieldSelection] = {}

        for selection in selection_set.selections:
            if isinstance(selection, FieldNode):
                field_name = selection.name.value
                alias = selection.alias.value if selection.alias else None
                arguments = self._extract_arguments(selection)

                if selection.selection_set:
                    nested = self._parse_selection_set(selection.selection_set)
                    nested.name = field_name
                    nested.alias = alias
                    nested.arguments = arguments
                    sub_fields[field_name] = nested
                else:
                    sub_fields[field_name] = FieldSelection(
                        name=field_name,
                        alias=alias,
                        arguments=arguments,
                    )

        return FieldSelection(sub_fields=sub_fields)

    def _extract_arguments(self, field_node: FieldNode) -> dict[str, Any]:
        """Extract arguments from a FieldNode into a dict."""
        args: dict[str, Any] = {}
        if not field_node.arguments:
            return args

        for arg in field_node.arguments:
            args[arg.name.value] = self._value_node_to_python(arg.value)

        return args

    def _value_node_to_python(self, value_node: Any) -> Any:
        """Convert a GraphQL ValueNode to a Python value.

        Delegates to graphql-core's ``value_from_ast_untyped`` so we share one
        implementation with the rest of the codebase. Variables are unresolved
        here (no variables dict is passed); the executor resolves them later
        via ``ArgumentBuilder``.
        """
        from graphql.utilities import value_from_ast_untyped

        return value_from_ast_untyped(value_node, None)
