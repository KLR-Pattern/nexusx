"""Query executor using level-by-level BFS DataLoader resolution."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from graphql import DocumentNode, FieldNode, OperationDefinitionNode
from pydantic import TypeAdapter
from sqlmodel import SQLModel

from nexusx.execution.argument_builder import ArgumentBuilder
from nexusx.loader.pagination import PageArgs, PageLoadCommand
from nexusx.query_parser import FieldSelection

if TYPE_CHECKING:
    from nexusx.loader.registry import ErManager, RelationshipInfo

logger = logging.getLogger(__name__)


@dataclass
class _FieldJob:
    """A single field's load task within one BFS level."""

    parents: list
    parent_entity: type[SQLModel]
    rel_info: RelationshipInfo
    child_sel: FieldSelection
    original_sel: FieldSelection | None = None


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

    def _store(self, entity: Any, field_name: str, value: Any) -> None:
        """Store resolved relationship value."""
        self._results[(id(entity), field_name)] = value

    def _retrieve(self, entity: Any, field_name: str) -> Any:
        """Retrieve resolved relationship value."""
        return self._results.get((id(entity), field_name))

    async def execute_query(
        self,
        document: DocumentNode,
        variables: dict[str, Any] | None,
        operation_name: str | None,
        parsed_selections: dict[str, FieldSelection],
        query_methods: dict[str, dict[str, tuple[type[SQLModel], Any]]],
        mutation_methods: dict[str, dict[str, tuple[type[SQLModel], Any]]],
        entities: list[type[SQLModel]],
    ) -> dict[str, Any]:
        """Execute a GraphQL query or mutation.

        Dispatch is two-level, mirroring the grouped schema: each top-level
        field is an entity group (``{ Entity { method {} } }``); the method
        fields live one level deeper on the ``{Entity}Query`` /
        ``{Entity}Mutation`` group type. ``query_methods`` / ``mutation_methods``
        are grouped as ``{entity_name: {method_name: (entity, method)}}``.
        """
        data: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        entity_names = {e.__name__ for e in entities}

        # Clear caches for this request
        self._registry.clear_cache()
        self._results.clear()

        for definition in document.definitions:
            if not isinstance(definition, OperationDefinitionNode):
                continue
            op_type = definition.operation.value
            grouped_methods = query_methods if op_type == "query" else mutation_methods
            group_suffix = op_type.title()  # "Query" or "Mutation"

            for selection in definition.selection_set.selections:
                if not isinstance(selection, FieldNode):
                    continue

                entity_name = selection.name.value

                # Introspection fields (query only) — not entity groups.
                if (
                    op_type == "query"
                    and self._introspection_generator is not None
                    and entity_name in {"__schema", "__type"}
                ):
                    data[entity_name] = self._introspection_generator.execute_field(
                        selection, variables
                    )
                    continue

                method_group = grouped_methods.get(entity_name)

                # Selected an entity group without any method subselection.
                if method_group is not None and selection.selection_set is None:
                    errors.append(
                        self._bare_group_field_error(entity_name, method_group)
                    )
                    continue

                if method_group is None:
                    errors.append(
                        {
                            "message": (
                                f"Cannot query field '{entity_name}' on type "
                                f"'{group_suffix}'"
                            ),
                            "path": [entity_name],
                        }
                    )
                    continue

                # Two-level: dispatch each method field inside the entity group.
                data[entity_name] = await self._execute_entity_group(
                    entity_name,
                    method_group,
                    selection,
                    parsed_selections,
                    variables,
                    entity_names,
                    group_suffix,
                    errors,
                )

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
    ) -> dict[str, Any]:
        """Execute every method field selected inside one entity group.

        Methods run sequentially (v1) to preserve the BFS DataLoader's
        store-then-read deduplication invariants across sibling fields.
        """
        entity_data: dict[str, Any] = {}
        group_sel = parsed_selections.get(entity_name)

        for method_node in group_selection.selection_set.selections:
            if not isinstance(method_node, FieldNode):
                continue
            method_name = method_node.name.value

            try:
                method_info = method_group.get(method_name)
                if method_info is None:
                    errors.append(
                        {
                            "message": (
                                f"Cannot query field '{method_name}' on type "
                                f"'{entity_name}{group_suffix}'"
                            ),
                            "path": [entity_name, method_name],
                        }
                    )
                    continue

                entity, method = method_info

                # Build arguments from the METHOD field node (second level).
                args = self._argument_builder.build_arguments(
                    method_node, variables, method, entity, entity_names
                )

                # Execute the method
                result = method(**args)
                if inspect.isawaitable(result):
                    result = await result

                # The method's selection tree is nested one level deeper than
                # the entity-group selection.
                field_sel = (
                    group_sel.sub_fields.get(method_name)
                    if group_sel and group_sel.sub_fields
                    else None
                )

                # Resolve relationships via BFS DataLoader
                if field_sel and result is not None:
                    await self._resolve_result(result, entity, field_sel)

                # Serialize
                entity_data[method_name] = self._serialize(result, entity, field_sel)

            except Exception as e:
                # Per-field exceptions are common (user input bugs, DB
                # constraint violations, resolver programming errors); the
                # response stays GraphQL-spec compliant ({message, path}) but
                # the server log retains the exception type and stack.
                logger.exception(
                    "Resolver error in field %s.%s", entity_name, method_name
                )
                errors.append(
                    {"message": str(e), "path": [entity_name, method_name]}
                )

        return entity_data

    @staticmethod
    def _bare_group_field_error(
        entity_name: str, method_group: dict[str, tuple[type[SQLModel], Any]]
    ) -> dict[str, Any]:
        """Build the friendly error for selecting a bare entity group field.

        Fires when a query selects ``{ Entity }`` with no method subselection.
        ``{ Entity {} }`` (empty braces) is rejected by graphql-core's parser
        before reaching the executor, so only the truly-bare case is caught.
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
            "path": [entity_name],
            "extensions": {
                "code": "BARE_GROUP_FIELD",
                "entity": entity_name,
                "available_methods": method_names,
            },
        }

    # ──────────────────────────────────────────────────────────
    # BFS resolution
    # ──────────────────────────────────────────────────────────

    async def _resolve_result(
        self,
        result: Any,
        entity: type[SQLModel],
        field_sel: FieldSelection,
    ) -> None:
        """Resolve relationships for a query result (single or list)."""
        if result is None:
            return

        if isinstance(result, list):
            await self._bfs_resolve(result, entity, field_sel)
        else:
            await self._bfs_resolve([result], entity, field_sel)

    async def _bfs_resolve(
        self,
        parents: list,
        parent_entity: type[SQLModel],
        field_sel: FieldSelection,
    ) -> None:
        """Level-by-level BFS relationship resolution using DataLoaders.

        At each level, all relationship fields are loaded concurrently via
        asyncio.gather. The loaded children become the parents for the next
        level.
        """
        queue: list[_FieldJob] = self._build_field_jobs(
            parents, parent_entity, field_sel
        )

        while queue:
            # Concurrent load all fields in this level
            load_results = await asyncio.gather(
                *(self._load_field(job) for job in queue)
            )

            # Build next level's jobs from loaded children
            next_jobs: list[_FieldJob] = []
            for job, children in zip(queue, load_results, strict=True):
                next_jobs.extend(
                    self._build_field_jobs(
                        children, job.rel_info.target_entity, job.child_sel
                    )
                )
            queue = next_jobs

    def _build_field_jobs(
        self,
        parents: list,
        parent_entity: type[SQLModel],
        field_sel: FieldSelection,
    ) -> list[_FieldJob]:
        """Extract relationship fields that need loading and build FieldJobs."""
        if not parents or not field_sel.sub_fields:
            return []

        jobs: list[_FieldJob] = []
        for field_name, child_sel in field_sel.sub_fields.items():
            rel_info = self._registry.get_relationship(parent_entity, field_name)
            if rel_info is None:
                continue

            if not child_sel.sub_fields:
                continue

            # Paginated: use items sub-selection for deeper resolution
            effective_sel = child_sel
            if (
                self._enable_pagination
                and rel_info.is_list
                and rel_info.page_loader is not None
            ):
                items_sel = (
                    child_sel.sub_fields.get("items")
                    if child_sel.sub_fields
                    else None
                )
                if items_sel and items_sel.sub_fields:
                    effective_sel = items_sel

            if not effective_sel.sub_fields:
                continue

            # Collect valid FK values
            fk_values = [getattr(p, rel_info.fk_field, None) for p in parents]
            valid_indices = [i for i, fk in enumerate(fk_values) if fk is not None]
            if not valid_indices:
                continue

            valid_parents = [parents[i] for i in valid_indices]
            jobs.append(
                _FieldJob(
                    parents=valid_parents,
                    parent_entity=parent_entity,
                    rel_info=rel_info,
                    child_sel=effective_sel,
                    original_sel=child_sel if effective_sel is not child_sel else None,
                )
            )
        return jobs

    async def _load_field(self, job: _FieldJob) -> list:
        """Load a single field's relationship data and store results.

        Returns a flat list of all loaded child entities for the next BFS level.
        """
        if (
            self._enable_pagination
            and job.rel_info.is_list
            and job.rel_info.page_loader is not None
        ):
            return await self._load_field_paginated(job)
        else:
            return await self._load_field_batch(job)

    async def _load_field_batch(self, job: _FieldJob) -> list:
        """Batch load a non-paginated relationship field."""
        from nexusx.loader.query_meta import (
            generate_query_meta_from_selection,
            generate_type_key_from_selection,
            merge_query_meta,
            set_query_meta,
        )

        rel_info = job.rel_info
        child_sel = job.child_sel

        # Build FK lookup from target entity's registered relationships
        target_rels = self._registry.get_relationships(rel_info.target_entity)
        fk_lookup = {name: info.fk_field for name, info in target_rels.items()}

        # Generate type_key for split mode (None in default mode)
        type_key = generate_type_key_from_selection(
            child_sel, rel_info.target_entity, fk_lookup=fk_lookup,
        )
        loader = self._registry.get_loader(rel_info.loader, type_key=type_key)

        # Inject _query_meta for SQL column pruning
        meta = generate_query_meta_from_selection(
            child_sel, rel_info.target_entity, fk_lookup=fk_lookup,
        )
        if type_key is not None and self._registry._split_mode:
            set_query_meta(loader, meta)
        else:
            merge_query_meta(loader, meta)

        fk_values = [getattr(p, rel_info.fk_field) for p in job.parents]
        results = await loader.load_many(fk_values)

        all_children: list = []
        for parent, result in zip(job.parents, results, strict=True):
            if rel_info.is_list:
                items = result or []
                self._store(parent, rel_info.name, items)
                all_children.extend(items)
            else:
                self._store(parent, rel_info.name, result)
                if result is not None:
                    all_children.append(result)
        return all_children

    async def _load_field_paginated(self, job: _FieldJob) -> list:
        """Load a paginated relationship field."""
        from nexusx.loader.query_meta import (
            generate_query_meta_from_selection,
            generate_type_key_from_selection,
            merge_query_meta,
            set_query_meta,
        )

        rel_info = job.rel_info
        child_sel = job.child_sel

        # Extract page args from original field selection (before items adjustment).
        # job.original_sel holds the original child_sel when it was replaced by
        # items_sel; otherwise fall back to child_sel (no pagination adjustment).
        page_args = self._extract_page_args(
            job.original_sel if job.original_sel is not None else child_sel,
            rel_info,
        )

        target_rels = self._registry.get_relationships(rel_info.target_entity)
        fk_lookup = {name: info.fk_field for name, info in target_rels.items()}

        type_key = generate_type_key_from_selection(
            child_sel, rel_info.target_entity, fk_lookup=fk_lookup,
        )
        loader = self._registry.get_loader(rel_info.page_loader, type_key=type_key)

        meta = generate_query_meta_from_selection(
            child_sel, rel_info.target_entity, fk_lookup=fk_lookup,
        )
        if type_key is not None and self._registry._split_mode:
            set_query_meta(loader, meta)
        else:
            merge_query_meta(loader, meta)

        fk_values = [getattr(p, rel_info.fk_field) for p in job.parents]
        commands = [
            PageLoadCommand(fk_value=fk, page_args=page_args) for fk in fk_values
        ]
        results = await loader.load_many(commands)

        all_children: list = []
        for parent, page_result in zip(job.parents, results, strict=True):
            self._store(parent, rel_info.name, page_result)
            if page_result and page_result.get("items"):
                all_children.extend(page_result["items"])
        return all_children

    def _extract_page_args(
        self, field_sel: FieldSelection, rel_info: RelationshipInfo
    ) -> PageArgs:
        """Extract PageArgs from GraphQL field arguments."""
        args = field_sel.arguments or {}
        return PageArgs(
            limit=args.get("limit"),
            offset=args.get("offset", 0),
            default_page_size=rel_info.default_page_size,
            max_page_size=rel_info.max_page_size,
        )

    # ──────────────────────────────────────────────────────────
    # Serialization (unchanged)
    # ──────────────────────────────────────────────────────────

    def _serialize(
        self,
        result: Any,
        entity: type[SQLModel],
        field_sel: FieldSelection | None,
    ) -> Any:
        """Serialize result to JSON-compatible dict."""
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
        if isinstance(item, dict):
            return item

        if not field_sel or not field_sel.sub_fields:
            # Fallback: use model_dump
            if hasattr(item, "model_dump"):
                return self._filter_output(item.model_dump(mode="json"), entity)
            return self._serialize_scalar_value(item)

        entity_rels = self._registry.get_relationships(entity)
        result = {}
        for field_name, child_sel in field_sel.sub_fields.items():
            rel_info = entity_rels.get(field_name)

            if rel_info is not None:
                value = self._retrieve(item, field_name)
                result[field_name] = self._serialize_relationship_value(
                    value, rel_info, child_sel
                )
            else:
                # Scalar field
                value = getattr(item, field_name, None)
                if isinstance(value, UUID):
                    value = str(value)
                result[field_name] = value

        return result

    def _serialize_scalar_value(self, value: Any) -> Any:
        """Serialize a non-entity scalar / list-of-scalars returned by a method.

        Delegates to Pydantic's ``TypeAdapter``, which handles UUID / datetime
        / date / time / Decimal / Enum / set / tuple uniformly. Pydantic model
        instances don't reach here — the caller routes them through
        ``model_dump(mode="json")``.
        """
        return TypeAdapter(type(value)).dump_python(value, mode="json")

    def _serialize_relationship_value(
        self,
        value: Any,
        rel_info: RelationshipInfo,
        child_sel: FieldSelection,
    ) -> Any:
        """Serialize a relationship value (list, single, or paginated result)."""
        if value is None:
            return None

        target = rel_info.target_entity

        if (
            self._enable_pagination
            and rel_info.is_list
            and isinstance(value, dict)
            and "items" in value
        ):
            # Paginated result: { items: [...], pagination: {...} }
            items = value.get("items", [])
            pagination = value.get("pagination")
            page_result: dict[str, Any] = {}
            wants_items = child_sel.sub_fields is not None and "items" in child_sel.sub_fields
            if wants_items:
                items_sel = child_sel.sub_fields.get("items") if child_sel.sub_fields else None
                page_result["items"] = [
                    self._serialize_item(v, target, items_sel)
                    for v in items if v is not None
                ]
            # Only include pagination if the user selected it in the query
            wants_pagination = (
                child_sel.sub_fields is not None and "pagination" in child_sel.sub_fields
            )
            if wants_pagination and pagination:
                # Filter pagination fields by user selection
                pag_sel = child_sel.sub_fields.get("pagination")
                pag_fields = (
                    set(pag_sel.sub_fields.keys())
                    if pag_sel and pag_sel.sub_fields
                    else None
                )
                if isinstance(pagination, dict):
                    raw = pagination
                else:
                    raw = pagination.model_dump(mode="json")
                if pag_fields:
                    page_result["pagination"] = {k: v for k, v in raw.items() if k in pag_fields}
                else:
                    page_result["pagination"] = raw
            return page_result

        if isinstance(value, list):
            return [
                self._serialize_item(v, target, child_sel)
                for v in value if v is not None
            ]

        if isinstance(value, dict):
            return value
        return self._serialize_item(value, target, child_sel)

    def _filter_output(
        self, data: dict[str, Any], entity: type[SQLModel]
    ) -> dict[str, Any]:
        """Remove FK fields and relationship fields from output dict."""
        fk_fields = self._get_fk_fields(entity)
        relationship_names = self._get_relationship_names(entity)
        excluded = fk_fields | relationship_names | {"metadata"}
        return {k: v for k, v in data.items() if k not in excluded}

    def _get_fk_fields(self, entity: type[SQLModel]) -> set[str]:
        """Get foreign key field names for an entity."""
        fk_fields: set[str] = set()
        for field_name, field_info in entity.model_fields.items():
            if hasattr(field_info, "foreign_key") and isinstance(
                field_info.foreign_key, str
            ):
                fk_fields.add(field_name)
            if hasattr(field_info, "metadata"):
                for meta in field_info.metadata:
                    if hasattr(meta, "foreign_key") and isinstance(
                        meta.foreign_key, str
                    ):
                        fk_fields.add(field_name)
        return fk_fields

    def _get_relationship_names(self, entity: type[SQLModel]) -> set[str]:
        """Get relationship field names for an entity."""
        names: set[str] = set()
        if hasattr(entity, "__sqlmodel_relationships__"):
            names.update(entity.__sqlmodel_relationships__.keys())
        try:
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(entity)
            if mapper and hasattr(mapper, "relationships"):
                names.update(mapper.relationships.keys())
        except Exception:
            pass
        return names
