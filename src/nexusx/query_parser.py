"""GraphQL query parser for extracting selection trees and arguments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graphql import DocumentNode, FieldNode, OperationDefinitionNode, parse


def _conflict_message(key: str, where: str) -> str:
    """Error text for a duplicate response key (specs/023 FR-007)."""
    return (
        f"Response key conflict: '{key}' is selected more than once at "
        f"'{where}'. Aliases, alias/field-name collisions, and plain "
        "duplicate fields all conflict — field merging is not supported."
    )


class ResponseKeyConflictError(ValueError):
    """Duplicate response key at one selection level (specs/023 FR-007).

    Raised by ``QueryParser`` for alias repeats, alias/field-name
    collisions, and plain duplicate fields — field merging is not
    supported. Subclasses ``ValueError`` so pre-023 ``except ValueError``
    callers keep working; handlers that want a machine-readable code catch
    this type specifically (compose maps it to ``ALIAS_CONFLICT``).
    """


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


def find_nested_alias(sel: FieldSelection) -> tuple[str, str] | None:
    """First alias strictly BELOW ``sel``, as ``(dotted_path, field_name)``.

    specs/023 FR-009 shared helper: nested-field aliases are out of scope on
    every execution path (entity-first serialization is lenient — unknown
    fields fall back to ``Any`` — so a nested alias would silently
    mis-project). All paths detect-and-reject through this single walk.

    ``dotted_path`` is the response-key path from ``sel`` down to the aliased
    node (e.g. ``"owner.reviews"``); ``field_name`` is the ORIGINAL field
    name of the aliased node (``child.name``), so error messages can render
    ``'reviews' aliased to 'r'`` instead of the bare alias key.
    """
    def _walk(selection: FieldSelection) -> tuple[str, str] | None:
        for key, child in (selection.sub_fields or {}).items():
            if child.alias is not None:
                return key, child.name
            deeper = _walk(child)
            if deeper is not None:
                return f"{key}.{deeper[0]}", deeper[1]
        return None

    return _walk(sel)


def nested_alias_message(dotted: str, field_name: str) -> str:
    """Error text for a nested-field alias (specs/023 FR-009).

    Shared by every reject site so the wording stays identical:
    ``Field aliases are not supported at nested level ('reviews' aliased
    to 'r'); only method-level aliases are supported``.
    """
    alias_key = dotted.rsplit(".", 1)[-1]
    return (
        "Field aliases are not supported at nested level "
        f"('{field_name}' aliased to '{alias_key}'); "
        "only method-level aliases are supported"
    )


class QueryParser:
    """Parses GraphQL queries to extract field selections and arguments."""

    def __init__(self, entity_field_names: set[str] | None = None):
        """Initialize the parser.

        Args:
            entity_field_names: Set of field names that represent entity types
                               (used to distinguish relationships from scalar fields).
        """
        self.entity_field_names = entity_field_names or set()

    def parse(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, FieldSelection]:
        """Parse a GraphQL query and return FieldSelection for each operation.

        Args:
            query: GraphQL query string.
            variables: Optional variables dict — when provided, query
                variables in arguments are resolved to their values (otherwise
                they surface as graphql's ``Undefined`` and must not reach
                argument consumers).

        Returns:
            Dictionary mapping operation name to FieldSelection.
        """
        return self.parse_document(parse(query), variables)

    def parse_document(
        self, document: DocumentNode, variables: dict[str, Any] | None = None
    ) -> dict[str, FieldSelection]:
        """Extract FieldSelection tree from an already-parsed DocumentNode.

        Use this when the caller has already parsed the query string (e.g. to
        share the AST with the executor) to avoid a second ``parse()`` pass.
        ``variables`` resolves query variables in arguments (specs/021
        hardening: without it, a variable argument becomes ``Undefined`` and
        pagination params crash downstream).

        specs/023: dict keys are RESPONSE keys (``alias or field_name``);
        ``FieldSelection.name`` keeps the original field name for lookups.
        Duplicate response keys at any level raise ``ValueError``.
        """
        result: dict[str, FieldSelection] = {}

        for definition in document.definitions:
            if isinstance(definition, OperationDefinitionNode):
                for selection in definition.selection_set.selections:
                    if isinstance(selection, FieldNode):
                        operation_name = selection.name.value
                        alias = (
                            selection.alias.value if selection.alias else None
                        )
                        key = alias or operation_name
                        if key in result:
                            raise ResponseKeyConflictError(
                                _conflict_message(key, "top level")
                            )
                        if selection.selection_set:
                            meta = self._parse_selection_set(
                                selection.selection_set, variables, path=key
                            )
                            meta.name = operation_name
                            meta.alias = alias
                            result[key] = meta

        return result

    def validate_no_aliases(self, query: str) -> None:
        """Reject GraphQL aliases explicitly.

        Optional user-side guard. Since specs/023 the built-in executors
        SUPPORT method-level aliases (response keys become the aliases), so
        nexusx no longer calls this internally — keep it for custom handlers
        that want to forbid aliases on their own surfaces.
        """
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

    def _parse_selection_set(
        self,
        selection_set: Any,
        variables: dict[str, Any] | None = None,
        path: str = "",
    ) -> FieldSelection:
        """Internal method to parse selection set into FieldSelection.

        specs/023: ``sub_fields`` is keyed by RESPONSE key (``alias or
        field_name``) so same-name fields with different aliases no longer
        overwrite each other (Issue #140). Duplicate response keys — alias
        repeats, alias/field-name collisions, and plain duplicate fields —
        raise ``ValueError`` (field merging is intentionally not supported).
        """
        sub_fields: dict[str, FieldSelection] = {}

        for selection in selection_set.selections:
            if isinstance(selection, FieldNode):
                field_name = selection.name.value
                alias = selection.alias.value if selection.alias else None
                key = alias or field_name
                if key in sub_fields:
                    raise ResponseKeyConflictError(
                        _conflict_message(key, path or "root")
                    )
                arguments = self._extract_arguments(selection, variables)

                if selection.selection_set:
                    nested = self._parse_selection_set(
                        selection.selection_set, variables,
                        path=f"{path}.{key}" if path else key,
                    )
                    nested.name = field_name
                    nested.alias = alias
                    nested.arguments = arguments
                    sub_fields[key] = nested
                else:
                    sub_fields[key] = FieldSelection(
                        name=field_name,
                        alias=alias,
                        arguments=arguments,
                    )

        return FieldSelection(sub_fields=sub_fields)

    def _extract_arguments(
        self, field_node: FieldNode, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Extract arguments from a FieldNode into a dict."""
        args: dict[str, Any] = {}
        if not field_node.arguments:
            return args

        for arg in field_node.arguments:
            args[arg.name.value] = self._value_node_to_python(arg.value, variables)

        return args

    def _value_node_to_python(
        self, value_node: Any, variables: dict[str, Any] | None = None
    ) -> Any:
        """Convert a GraphQL ValueNode to a Python value.

        Delegates to graphql-core's ``value_from_ast_untyped`` so we share one
        implementation with the rest of the codebase. When ``variables`` is
        provided, query variables resolve to their values; without it a
        VariableNode becomes graphql's ``Undefined`` (the executor's
        ``ArgumentBuilder`` resolves variables independently for method calls).
        """
        from graphql.utilities import value_from_ast_untyped

        return value_from_ast_untyped(value_node, variables)
