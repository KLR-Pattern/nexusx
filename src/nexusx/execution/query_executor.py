"""Query executor using level-by-level BFS DataLoader resolution."""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any

from graphql import DocumentNode, FieldNode, OperationDefinitionNode
from pydantic import BaseModel, TypeAdapter
from sqlmodel import SQLModel

from nexusx.execution.argument_builder import ArgumentBuilder
from nexusx.loader.pagination import KeyedPaginatedPackage, PaginatedPackage
from nexusx.loader.registry import RelationshipKind
from nexusx.query_parser import (
    FieldSelection,
    ParsedOperation,
    find_nested_alias,
    nested_alias_message,
)
from nexusx.response_builder import (
    get_relation_entity,
    get_relationship_names,
    serialize_with_model,
)
from nexusx.utils.pagination_schema import is_active_paginated_relationship
from nexusx.utils.type_utils import get_fk_fields

if TYPE_CHECKING:
    from nexusx.loader.registry import ErManager

logger = logging.getLogger(__name__)

_CACHE_MISS = object()


def _node_key(node: FieldNode) -> str:
    """Response key of a field node: alias when present, else field name.

    specs/023: mirrors ``QueryParser`` key semantics so executor lookups
    into ``parsed_selections`` and ``sub_fields`` stay aligned when the
    query carries aliases.
    """
    return node.alias.value if node.alias else node.name.value


class QueryExecutor:
    """Executes GraphQL queries using DataLoader for relationship resolution.

    Uses a separate _results dict to store resolved relationship data
    (including paginated results) since SQLAlchemy relationship fields
    cannot hold dict values.

    Execution flow:
    1. Execute root query method → get root entity instances
    2. BFS resolve: level-by-level batch load via DataLoader (concurrent per level)
    3. Build response from resolved data
    """

    def __init__(
        self,
        loader_registry: ErManager,
        enable_pagination: bool = False,
        introspection_generator: Any | None = None,
    ):
        self._registry = loader_registry
        self._enable_pagination = enable_pagination
        self._introspection_generator = introspection_generator
        self._argument_builder = ArgumentBuilder()
        # (id(entity), field_name) -> resolved value
        self._results: dict[tuple[int, str], Any] = {}
        # Lazily-built Resolver used for entity-field BFS dispatch (US3).
        self._entity_resolver: Any = None

    def _store(self, entity: Any, field_name: str, value: Any) -> None:
        """Store resolved relationship value."""
        self._results[(id(entity), field_name)] = value

    def _retrieve(self, entity: Any, field_name: str) -> Any:
        """Retrieve resolved relationship value."""
        return self._results.get((id(entity), field_name), _CACHE_MISS)

    async def execute_query(
        self,
        document: DocumentNode,
        variables: dict[str, Any] | None,
        operation_name: str | None,
        parsed_selections: dict[str, FieldSelection] | None,
        query_methods: dict[str, dict[str, tuple[type[SQLModel], Any]]],
        mutation_methods: dict[str, dict[str, tuple[type[SQLModel], Any]]],
        entities: list[type[SQLModel]],
        *,
        parsed_operations: list[ParsedOperation] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query or mutation.

        Dispatch is two-level, mirroring the grouped schema: each top-level
        field is an entity group (``{ Entity { method {} } }``); the method
        fields live one level deeper on the ``{Entity}Query`` /
        ``{Entity}Mutation`` group type. ``query_methods`` / ``mutation_methods``
        are grouped as ``{entity_name: {method_name: (entity, method)}}``.

        Operation selection (issue #142): pass ``parsed_operations`` (from
        ``QueryParser.parse_operations``) and exactly ONE operation is
        selected and executed per GraphQL spec — ``operation_name`` matches
        a named operation; a single anonymous operation runs as-is; several
        operations without a name is an error. Same-name groups in
        different operations can no longer cross-contaminate their
        projections. The legacy path (``parsed_selections`` only, no
        ``parsed_operations``) keeps executing every definition for
        backward compatibility with direct callers.
        """
        data: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        entity_names = {e.__name__ for e in entities}
        # specs/023 FR-006 (operation-scope fail-stop): once a mutation
        # fails, every later mutation in the same operation is skipped —
        # across entity-group boundaries, matching GraphQL's operation-level
        # serial mutation semantics. Queries are unaffected.
        mutation_aborted = False

        # Clear caches for this request
        self._registry.clear_cache()
        self._results.clear()

        if parsed_operations is not None:
            selected = self._select_operation(parsed_operations, operation_name)
            if isinstance(selected, dict):
                return selected  # selection error response
            definitions: list[Any] = [selected.definition]
            active_selections = selected.selections
        else:
            if parsed_selections is None:
                raise ValueError(
                    "execute_query requires either parsed_selections "
                    "(legacy all-definitions path) or parsed_operations "
                    "(spec-compliant single-operation path)"
                )
            definitions = list(document.definitions)
            active_selections = parsed_selections

        for definition in definitions:
            if not isinstance(definition, OperationDefinitionNode):
                continue
            op_type = definition.operation.value
            grouped_methods = query_methods if op_type == "query" else mutation_methods
            group_suffix = op_type.title()  # "Query" or "Mutation"

            for selection in definition.selection_set.selections:
                if not isinstance(selection, FieldNode):
                    continue

                entity_name = selection.name.value
                # specs/023 P2: data keys and error paths use RESPONSE keys
                # (``alias or name``) per the GraphQL spec; ``entity_name``
                # stays the lookup identity and powers human-facing logs /
                # messages.
                group_key = _node_key(selection)

                # Introspection fields (query only) — not entity groups.
                if (
                    op_type == "query"
                    and self._introspection_generator is not None
                    and entity_name in {"__schema", "__type"}
                ):
                    data[group_key] = self._introspection_generator.execute_field(
                        selection, variables
                    )
                    continue

                method_group = grouped_methods.get(entity_name)

                # Selected an entity group without any method subselection.
                if method_group is not None and selection.selection_set is None:
                    errors.append(
                        self._bare_group_field_error(
                            entity_name, method_group, group_key
                        )
                    )
                    continue

                if method_group is None:
                    errors.append(
                        {
                            "message": (
                                f"Cannot query field '{entity_name}' on type "
                                f"'{group_suffix}'"
                            ),
                            "path": [group_key],
                        }
                    )
                    continue

                # Two-level: dispatch each method field inside the entity group.
                # specs/023: mutation groups fail-stop (serial semantics);
                # query groups keep executing siblings past a failure.
                entity_data, aborted = await self._execute_entity_group(
                    entity_name,
                    method_group,
                    selection,
                    active_selections,
                    variables,
                    entity_names,
                    group_suffix,
                    errors,
                    fail_stop=(op_type == "mutation"),
                    prior_aborted=mutation_aborted,
                )
                data[group_key] = entity_data
                mutation_aborted = mutation_aborted or aborted

        response: dict[str, Any] = {}
        if data:
            response["data"] = data
        if errors:
            response["errors"] = errors
        return response

    async def _execute_entity_group(
        self,
        entity_name: str,
        method_group: dict[str, tuple[type[SQLModel], Any]],
        group_selection: FieldNode,
        parsed_selections: dict[str, FieldSelection],
        variables: dict[str, Any] | None,
        entity_names: set[str],
        group_suffix: str,
        errors: list[dict[str, Any]],
        *,
        fail_stop: bool = False,
        prior_aborted: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        """Execute every method field selected inside one entity group.

        Methods run sequentially (v1) to preserve the BFS DataLoader's
        store-then-read deduplication invariants across sibling fields.

        specs/023 (D4): failures are per-field — a failing method nulls its
        own response key with an errors entry; sibling results are kept
        (replaces the pre-023 whole-group nulling). With ``fail_stop``
        (mutation groups), every method after the first failure is skipped
        and marked SKIPPED_PRIOR_FAILURE.

        Returns ``(entity_data, aborted)``: the second value tells the
        caller a mutation failed here (or the abort was inherited) so later
        groups in the same operation can skip their mutations too — FR-006
        operation-scope fail-stop. Only meaningful with ``fail_stop``;
        query groups always report ``False``.
        """
        entity_data: dict[str, Any] = {}
        # An inherited abort (a mutation failed in a PRIOR group of this
        # operation) starts the group already in fail-stop.
        group_failed = fail_stop and prior_aborted
        # specs/023 P2: response key of the group (alias when present) —
        # error paths use it so clients can locate errors inside the data
        # they actually received; ``entity_name`` remains the lookup/log name.
        group_key = _node_key(group_selection)
        group_sel = parsed_selections.get(group_key)

        for method_node in group_selection.selection_set.selections:
            if not isinstance(method_node, FieldNode):
                continue
            method_name = method_node.name.value
            response_key = _node_key(method_node)

            if group_failed:
                # fail-stop (mutations): skipped keys stay null + flagged.
                entity_data[response_key] = None
                errors.append(
                    {
                        "message": (
                            f"Skipped '{response_key}' because a prior "
                            "mutation failed"
                        ),
                        "path": [group_key, response_key],
                        "extensions": {"code": "SKIPPED_PRIOR_FAILURE"},
                    }
                )
                continue

            try:
                method_info = method_group.get(method_name)
                if method_info is None:
                    errors.append(
                        {
                            "message": (
                                f"Cannot query field '{method_name}' on type "
                                f"'{entity_name}{group_suffix}'"
                            ),
                            "path": [group_key, response_key],
                        }
                    )
                    continue

                entity, method = method_info

                # The method's selection tree is nested one level deeper than
                # the entity-group selection.
                field_sel = (
                    group_sel.sub_fields.get(response_key)
                    if group_sel and group_sel.sub_fields
                    else None
                )

                func = method.__func__ if hasattr(method, "__func__") else method
                pag_root = getattr(func, "_pagination_root", None)
                is_pagination_root = pag_root is not None
                # ``by_<key>_in`` batch roots are federation machine-facing:
                # mounters' remote loaders select DTO-side computed fields the
                # member never serves (dropped by design, recomputed
                # mounter-side) — exempt them from strict selection validation.
                is_federation_batch_root = bool(
                    getattr(func, "_nexusx_federation_batch_root", None)
                )

                # Validate the selection against the entity BEFORE executing:
                # an unknown field must surface as a GraphQL-style error here,
                # not be silently dropped at serialization (empty-object rows).
                if not is_federation_batch_root and not self._validate_method_selection(
                    entity,
                    field_sel,
                    [group_key, response_key],
                    pag_root=pag_root,
                    errors=errors,
                ):
                    continue

                # Build arguments from the METHOD field node (second level).
                args = self._argument_builder.build_arguments(
                    method_node, variables, method, entity, entity_names
                )
                if is_pagination_root:
                    pagination_field = (
                        field_sel.sub_fields.get("pagination")
                        if field_sel and field_sel.sub_fields
                        else None
                    )
                    pagination_fields = (
                        set(pagination_field.sub_fields)
                        if pagination_field and pagination_field.sub_fields
                        else set()
                    )
                    # Private execution metadata: the generated root accepts
                    # **kwargs at runtime, while its public GraphQL signature
                    # remains limited to the declared pagination arguments.
                    args["__nexusx_pagination_selection"] = pagination_fields

                # Execute the method
                result = method(**args)
                if inspect.isawaitable(result):
                    result = await result

                # Resolve relationships via BFS DataLoader
                if field_sel and result is not None:
                    await self._resolve_result(
                        result, entity, field_sel,
                        is_pagination_root=is_pagination_root,
                    )

                # Serialize
                entity_data[response_key] = self._serialize(
                    result, entity, field_sel
                )

            except Exception as e:
                # Per-field exceptions are common (user input bugs, DB
                # constraint violations, resolver programming errors); the
                # response stays GraphQL-spec compliant ({message, path,
                # extensions}) while the server log retains the exception
                # type and stack. specs/023 (D4): the failed method nulls
                # only its own response key — sibling results survive.
                # fail_stop (mutation groups) skips the remainder.
                logger.exception(
                    "Resolver error in field %s.%s", entity_name, method_name
                )
                entity_data[response_key] = None
                errors.append(
                    {
                        "message": str(e),
                        "path": [group_key, response_key],
                        "extensions": {"code": "RESOLVER_ERROR"},
                    }
                )
                group_failed = fail_stop

        return entity_data, group_failed

    @staticmethod
    def _select_operation(
        operations: list[ParsedOperation],
        operation_name: str | None,
    ) -> ParsedOperation | dict[str, Any]:
        """Pick the one operation to execute, per the GraphQL spec.

        ``operation_name`` matches a named operation; a single operation
        runs as-is; several operations without a name is an error (issue
        #142: the pre-fix behavior executed ALL of them with
        cross-contaminated selections). Error wording mirrors graphql-core.
        Returns the selected ``ParsedOperation``, or an error-response dict.
        """
        if operation_name is not None:
            for op in operations:
                if op.name == operation_name:
                    return op
            return {
                "errors": [
                    {"message": f"Unknown operation named '{operation_name}'."}
                ]
            }
        if len(operations) == 1:
            return operations[0]
        if not operations:
            return {"errors": [{"message": "Must provide an operation."}]}
        return {
            "errors": [
                {
                    "message": (
                        "Must provide operation name if query contains "
                        "multiple operations."
                    )
                }
            ]
        }

    @staticmethod
    def _bare_group_field_error(
        entity_name: str,
        method_group: dict[str, tuple[type[SQLModel], Any]],
        group_key: str | None = None,
    ) -> dict[str, Any]:
        """Build the friendly error for selecting a bare entity group field.

        Fires when a query selects ``{ Entity }`` with no method subselection.
        ``{ Entity {} }`` (empty braces) is rejected by graphql-core's parser
        before reaching the executor, so only the truly-bare case is caught.
        ``group_key`` (specs/023 P2) is the response key for the error path
        when the group is aliased; defaults to the entity name.
        """
        method_names = sorted(method_group)
        first = method_names[0] if method_names else "method_name"
        example = f"{{ {entity_name} {{ {first}(id: 1) {{ id }} }} }}"
        return {
            "message": (
                f"Field '{entity_name}' is a grouping field that requires a "
                f"method subselection. Available methods on '{entity_name}': "
                f"{', '.join(method_names)}.\n"
                f"Example: {example}"
            ),
            "path": [group_key or entity_name],
            "extensions": {
                "code": "BARE_GROUP_FIELD",
                "entity": entity_name,
                "available_methods": method_names,
            },
        }

    # ──────────────────────────────────────────────────────────
    # Selection validation (pre-execution)
    # ──────────────────────────────────────────────────────────

    def _validate_method_selection(
        self,
        entity: type,
        field_sel: FieldSelection | None,
        path: list[str],
        *,
        pag_root: Any | None,
        errors: list[dict[str, Any]],
    ) -> bool:
        """Validate a method's field selection against its entity.

        Returns True when the whole selection is valid; otherwise appends
        one error per unknown field and returns False (the caller skips
        executing the method, mirroring the unknown-method handling).

        Pagination roots (``page_by_*``) validate as a package selection
        (``_validate_paginated_package``): only ``fk``, ``items`` and
        ``pagination`` are legal keys; the ``items`` subtree holds the
        entity fields.
        """
        if field_sel is None or not field_sel.sub_fields:
            return True

        # specs/023 FR-009: aliases below method level are out of scope —
        # reject loudly (before execution) instead of silently mis-projecting.
        nested = find_nested_alias(field_sel)
        if nested is not None:
            dotted, field_name = nested
            errors.append({
                "message": nested_alias_message(dotted, field_name),
                "path": [*path, dotted],
            })
            return False

        if pag_root is None:
            return self._validate_entity_fields(entity, field_sel, path, errors)

        return self._validate_paginated_package(
            entity,
            field_sel,
            path,
            errors,
            type_label=pag_root.package_name,
            extra_keys=frozenset({pag_root.fk_field}),
        )

    def _validate_paginated_package(
        self,
        entity: type,
        sel: FieldSelection,
        path: list[str],
        errors: list[dict[str, Any]],
        *,
        type_label: str,
        extra_keys: frozenset[str] = frozenset(),
    ) -> bool:
        """Validate a paginated package selection at one level.

        Shared by both paginated shapes, which differ only in wrapper name
        and key set: relationship fields (``{Target}Result`` — items +
        pagination) and federation pagination roots
        (``{Entity}{Field}PagePackage`` — fk + items + pagination, the fk
        passed via ``extra_keys``). ``pagination`` is a metadata subtree
        (its keys are filtered per request at serialization, not entity
        fields); ``items`` recurses into entity fields; any other key is
        rejected naming the wrapper type.
        """
        ok = True
        for key, child in sel.sub_fields.items():
            if key == "pagination":
                continue
            if key == "items":
                if child and child.sub_fields:
                    ok = (
                        self._validate_entity_fields(
                            entity, child, [*path, "items"], errors
                        )
                        and ok
                    )
                continue
            if key in extra_keys:
                continue
            errors.append(
                {
                    "message": (
                        f"Cannot query field '{key}' on type '{type_label}'"
                    ),
                    "path": [*path, key],
                }
            )
            ok = False
        return ok

    def _validate_entity_fields(
        self,
        entity: type,
        sel: FieldSelection,
        path: list[str],
        errors: list[dict[str, Any]],
    ) -> bool:
        """Validate field names at one entity level; recurse into relationships.

        A field is valid when it is an entity column (``model_fields`` — FK
        columns are queryable even though the SDL omits them) or a
        relationship, resolved through the same sources the serializer uses
        (loader registry first, then SQLAlchemy / SQLModel / annotations via
        ``get_relation_entity``). Unknown fields append a GraphQL-style
        validation error instead of being silently dropped later.
        """
        model_fields = getattr(entity, "model_fields", None) or {}
        fed_ns = self._get_federation_namespace()
        ok = True

        for fname, sub in sel.sub_fields.items():
            if fname == "__typename":
                continue
            if fname in model_fields:
                continue

            target, rel_info = self._relation_target(entity, fname, fed_ns)
            if target is None:
                errors.append(
                    {
                        "message": (
                            f"Cannot query field '{fname}' on type "
                            f"'{entity.__name__}'"
                        ),
                        "path": [*path, fname],
                    }
                )
                ok = False
                continue

            if sub is None or not sub.sub_fields:
                continue

            if is_active_paginated_relationship(
                rel_info, self._enable_pagination
            ):
                # Paginated relationships render as ``{Target}Result`` — the
                # selection is a package ``{ items {...} pagination {...} }``.
                ok = (
                    self._validate_paginated_package(
                        target,
                        sub,
                        [*path, fname],
                        errors,
                        type_label=f"{target.__name__}Result",
                    )
                    and ok
                )
            else:
                ok = (
                    self._validate_entity_fields(
                        target, sub, [*path, fname], errors
                    )
                    and ok
                )
        return ok

    def _relation_target(
        self,
        entity: type,
        fname: str,
        fed_ns: dict[str, type] | None,
    ) -> tuple[type | None, Any]:
        """Target entity class + RelationshipInfo for a relationship field.

        Returns ``(None, None)`` when ``fname`` is not a relationship.
        Resolution order mirrors serialization: loader registry (custom
        ``__relationships__`` + federation remotes; may also hold local ORM
        rels) before ``get_relation_entity`` (SQLAlchemy mapper →
        SQLModel → annotations). Only BaseModel-ish targets count as
        relationships — the annotations fallback also returns scalar types.
        """
        rel_info = self._registry.get_relationship(entity, fname)
        if rel_info is not None:
            target = getattr(rel_info, "target_entity", None)
            if isinstance(target, type) and hasattr(target, "model_fields"):
                return target, rel_info
            return None, None

        rel = get_relation_entity(
            entity,
            fname,
            federation_namespace=fed_ns,
            relation_entity_resolver=self._registry.get_relationship,
        )
        if isinstance(rel, type) and issubclass(rel, BaseModel):
            return rel, None
        return None, None

    # ──────────────────────────────────────────────────────────
    # Relationship resolution (delegated to Resolver — specs/018 US3)
    #
    # The level-by-level BFS + β ``fetch_remote_subtree`` dispatch moved into
    # ``Resolver._bfs_dispatch_entity_fields`` (US3 / T016-T018). The executor
    # now only delegates and stores results into ``self._results`` for
    # ``_serialize`` to read back — no federation import remains here.
    # ──────────────────────────────────────────────────────────

    async def _resolve_result(
        self,
        result: Any,
        entity: type[SQLModel],
        field_sel: FieldSelection,
        *,
        is_pagination_root: bool = False,
    ) -> None:
        """Resolve relationships for a query result (single or list).

        Delegates the level-by-level BFS to
        ``Resolver._bfs_dispatch_entity_fields`` (specs/018 US3). Resolved
        relationship values are written into ``self._results`` via the
        ``store`` callback and read back by ``_serialize`` — unchanged from
        the executor's former in-house BFS.

        When ``is_pagination_root`` is set (the caller derived it from
        ``func._pagination_root`` before the method ran), the result is a list
        of per-key packages ``{fk, items:[entity], pagination}``; BFS proceeds
        into each package's ``items`` entities (US2: items subtree recursion),
        not the packages themselves — mirroring the local paginated loader's
        ``all_children.extend(items)`` on the root path. Branching on the flag
        (a known fact) instead of sniffing the result shape avoids misrouting a
        plain ``list[dict]`` query whose first row happens to carry
        ``items``/``pagination`` keys.
        """
        if result is None:
            return

        if is_pagination_root:
            if isinstance(result, list) and result:
                items_sel = (
                    field_sel.sub_fields.get("items")
                    if field_sel and field_sel.sub_fields
                    else None
                )
                if items_sel is not None:
                    all_items: list = []
                    for pkg in result:
                        all_items.extend(pkg.items)
                    if all_items:
                        await self._dispatch_entity_fields(all_items, entity, items_sel)
            return

        if isinstance(result, list):
            await self._dispatch_entity_fields(result, entity, field_sel)
        else:
            await self._dispatch_entity_fields([result], entity, field_sel)

    async def _dispatch_entity_fields(
        self,
        parents: list,
        entity: type[SQLModel],
        field_sel: FieldSelection,
    ) -> None:
        """Delegate BFS relationship resolution to the Resolver (specs/018 US3).

        β ``fetch_remote_subtree`` dispatch now lives inside the Resolver
        (``Resolver._bfs_dispatch_entity_fields``), so the executor no longer
        imports or calls ``fetch_remote_subtree`` — federation fetch has
        collapsed into the Resolver alongside the γ DTO dispatch. Resolved
        relationship values are written back into ``self._results`` via the
        ``store`` callback; ``_serialize`` reads them exactly as before.
        """
        resolver = self._get_entity_resolver()
        # specs/019: inject a paged_provider closure (encapsulates gql args →
        # Paged merge) so the Resolver stays gql-agnostic. None when pagination
        # is off (plain relationship loads need no provider).
        paged_provider = self._make_paged_provider() if self._enable_pagination else None
        await resolver._bfs_dispatch_entity_fields(
            parents,
            entity,
            field_sel,
            store=self._store,
            enable_pagination=self._enable_pagination,
            paged_provider=paged_provider,
        )

    def _make_paged_provider(self) -> Any:
        """Build the ``paged_provider`` closure (specs/019).

        Encapsulates the gql → Paged merge (default from RelationshipInfo + gql
        args override via ``Resolver._merge_paged``). This is the ONLY place
        ``field_sel.arguments`` is read for pagination; the closure is injected
        per-call into ``Resolver._bfs_dispatch_entity_fields``, keeping the
        Resolver free of gql knowledge. Stateless (closes over nothing), so it
        could be cached at executor level — left per-call for simplicity.
        """
        from nexusx.resolver import Resolver

        def provider(rel_info: Any, field_sel: Any, field_name: str) -> Any:
            return Resolver._merge_paged(
                _rel_default_paged(rel_info),
                _gql_args_to_paged(field_sel, field_name),
            )

        return provider

    def _get_entity_resolver(self) -> Any:
        """Lazily build the Resolver instance used for entity-field dispatch.

        Created on first use (the ErManager must be fully wired before
        ``create_resolver()`` freezes it). Cached afterwards —
        ``_bfs_dispatch_entity_fields`` carries no per-call Resolver state (it
        dispatches straight through the request-scoped ErManager loaders), so a
        single instance serves every query on this executor.
        """
        if self._entity_resolver is None:
            self._entity_resolver = self._registry.create_resolver()()
        return self._entity_resolver

    # ──────────────────────────────────────────────────────────
    # Serialization (unchanged)
    # ──────────────────────────────────────────────────────────

    def _serialize_via_response_builder(
        self,
        item: Any,
        entity: type[SQLModel],
        field_sel: FieldSelection | None,
    ) -> Any:
        """Serialize a single entity-shaped result via response_builder (specs/018 US1).

        Routes through ``serialize_with_model`` (model-based field filtering)
        instead of the legacy dict-based loop in ``_serialize_item``. The
        output MUST be dict-equal to legacy for any entity-with-field_sel
        input — equivalence is verified by tests/test_query_executor_dto_first.py.

        ``federation_namespace`` is sourced from ``ErManager._fed_registry``
        (set by ``federate()``); when None (no federation), response_builder
        falls back to local SQLModel subclasses only.

        ``relation_entity_resolver`` lets response_builder find
        federation-materialized relationships (fields declared via
        ``__relationships__ = [RemoteRelationship(...)]``); these live in
        ``ErManager._registry`` and are invisible to SQLAlchemy /
        ``__annotations__`` lookups. specs/018 T002b.

        ``value_accessor`` checks ``self._results`` (BFS-resolved relationship
        cache) BEFORE ``getattr`` — without this, accessing a relationship
        attribute on a detached SQLModel instance triggers SQLAlchemy
        ``DetachedInstanceError`` (the session was closed post-query; the
        resolved values live in ``_results``, not in the DB).
        """
        federation_namespace = self._get_federation_namespace()

        def accessor(value: Any, field_name: str) -> Any:
            cached = self._retrieve(value, field_name)
            if cached is not _CACHE_MISS:
                return cached

            rel_info = self._registry.get_relationship(type(value), field_name)
            if (
                rel_info is not None
                and rel_info.kind != RelationshipKind.REMOTE_COALESCED
                and not rel_info.is_list
                and getattr(value, rel_info.fk_field, _CACHE_MISS) is None
            ):
                return None
            return getattr(value, field_name, None)

        def resolver(ent: Any, fname: str) -> Any:
            """Return RelationshipInfo for federation-materialized fields.

            Returns the RelationshipInfo object directly (response_builder
            unwraps ``.target_entity`` and reads ``.is_list``); None for
            local SQLModel relationships — those resolve via the SQLAlchemy /
            annotations fallback in get_relation_entity.
            """
            rel_info = self._registry.get_relationship(ent, fname)
            return rel_info

        return serialize_with_model(
            item, entity, None,
            federation_namespace=federation_namespace,
            value_accessor=accessor,
            relation_entity_resolver=resolver,
            _selection=field_sel,
        )

    def _get_federation_namespace(self) -> dict[str, type] | None:
        """Return the federation materialized-type namespace, if any.

        ``ErManager._fed_registry`` is set by ``federate()``; its ``_namespace``
        maps ``__name__`` to the materialized pydantic type. None when the
        handler is not federated.
        """
        fed_registry = getattr(self._registry, "_fed_registry", None)
        if fed_registry is None:
            return None
        return getattr(fed_registry, "_namespace", None)

    def _serialize(
        self,
        result: Any,
        entity: type[SQLModel],
        field_sel: FieldSelection | None,
    ) -> Any:
        """Serialize result to JSON-compatible dict.

        Entity-shaped results route through ``response_builder`` (specs/018 US1
        + Phase 7 T028 — the legacy dict-based loop is removed); scalar / dict
        / paginated-package returns use the dedicated branches below. Failures
        on the response_builder path propagate — no fallback (spec clarify Q3:
        fail-fast prevents hidden issues).
        """
        if result is None:
            return None

        if isinstance(result, list):
            return [self._serialize_item(item, entity, field_sel) for item in result]

        return self._serialize_item(result, entity, field_sel)

    def _serialize_item(
        self,
        item: Any,
        entity: type[SQLModel],
        field_sel: FieldSelection | None,
    ) -> dict[str, Any]:
        """Serialize a single entity or page result to dict."""
        if isinstance(item, PaginatedPackage):
            # A page_by_<key>_in root returns per-key packages; serialize specially.
            return self._serialize_paginated_package(item, entity, field_sel)
        if isinstance(item, dict):
            return item

        if not field_sel or not field_sel.sub_fields:
            # Fallback: use model_dump
            if hasattr(item, "model_dump"):
                return self._filter_output(item.model_dump(mode="json"), entity)
            return self._serialize_scalar_value(item)

        # Entity instance with field_sel: response_builder is the only path
        # (specs/018 US1 + Phase 7 T028 — legacy dict-based loop removed).
        return self._serialize_via_response_builder(item, entity, field_sel)

    def _serialize_paginated_package(
        self,
        pkg: dict[str, Any],
        entity: type[SQLModel],
        field_sel: FieldSelection | None,
    ) -> dict[str, Any]:
        """Serialize a paginated root's per-key package ``{fk, items, pagination}``.

        Reached when a ``page_by_<key>_in`` root returns per-key packages.
        ``items`` holds entity instances (serialized with the items sub-selection);
        ``pagination`` is filtered by the client's selection. (US1: scalar items;
        US2/T014 adds recursion into items' relationships via BFS.)
        """
        result: dict[str, Any] = {}
        sub = (
            field_sel.sub_fields if field_sel and field_sel.sub_fields else {}
        )
        items_sel = sub.get("items")
        if items_sel is not None:
            items = pkg.items
            result["items"] = [
                self._serialize_item(it, entity, items_sel)
                for it in items if it is not None
            ]
        pag_field = sub.get("pagination")
        if pag_field is not None:
            pag_sub = getattr(pag_field, "sub_fields", None) or {}
            pagination = pkg.pagination
            if pagination is None:
                pagination = {}
            elif hasattr(pagination, "model_dump"):
                pagination = pagination.model_dump(mode="json")
            if pag_sub:
                result["pagination"] = {
                    k: v for k, v in pagination.items() if k in pag_sub
                }
            else:
                result["pagination"] = pagination
        # Carry through the per-key fk field (KeyedPaginatedPackage only).
        if isinstance(pkg, KeyedPaginatedPackage) and pkg.fk_field in sub:
            result[pkg.fk_field] = pkg.fk_value
        return result

    def _serialize_scalar_value(self, value: Any) -> Any:
        """Serialize a non-entity scalar / list-of-scalars returned by a method.

        Delegates to Pydantic's ``TypeAdapter``, which handles UUID / datetime
        / date / time / Decimal / Enum / set / tuple uniformly. Pydantic model
        instances don't reach here — the caller routes them through
        ``model_dump(mode="json")``.
        """
        return TypeAdapter(type(value)).dump_python(value, mode="json")

    def _filter_output(
        self, data: dict[str, Any], entity: type[SQLModel]
    ) -> dict[str, Any]:
        """Remove FK fields and relationship fields from output dict."""
        fk_fields = get_fk_fields(entity)
        relationship_names = get_relationship_names(entity)
        excluded = fk_fields | relationship_names | {"metadata"}
        return {k: v for k, v in data.items() if k not in excluded}

def _gql_args_to_paged(
    field_sel: FieldSelection | None, field_name: str
) -> Any:
    """gql field args → ``Paged`` (specs/019). The single place entity-first
    gql's ``field_sel.arguments`` is read for pagination — lives outside the
    Resolver so the Resolver stays gql-agnostic. Delegates to
    ``_PagedOverride.from_dict`` (specs/021 P1-8); a None result means no
    caller args (``_merge_paged`` treats it as no override).
    """
    from nexusx.loader.pagination import _PagedOverride

    child = (
        field_sel.sub_fields.get(field_name)
        if field_sel and field_sel.sub_fields
        else None
    )
    args = (child.arguments if child else None) or {}
    return _PagedOverride.from_dict(args)


def _rel_default_paged(rel_info: Any) -> Any:
    """``RelationshipInfo`` → default ``Paged`` (specs/019).

    β (entity-first gql) has no field-level Paged default (unlike γ's
    ``__paged_fields__``), so only ``order`` is derivable — from
    ``page_capability.default_order``. ``limit`` / ``offset`` / ``direction``
    have no rel-level default (None / 0 / None); the page_loader's
    ``default_page_size`` applies separately as a ``PageArgs`` boundary in the
    Resolver.
    """
    from nexusx.loader.pagination import Paged

    order = None
    cap = getattr(rel_info, "page_capability", None)
    if cap is not None:
        order = getattr(cap, "default_order", None)
    return Paged(order=order)
