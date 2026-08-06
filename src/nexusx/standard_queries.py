"""Standard query generators for SQLModel entities.

This module provides automatic generation of standard queries (by_id, by_filter)
for SQLModel entities. Queries only load scalar fields; relationships are
resolved separately via DataLoader.
"""

from __future__ import annotations

import inspect
import re
import types
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import Field, create_model
from sqlmodel import SQLModel, select

from nexusx.decorator import query
from nexusx.utils.type_utils import get_fk_fields

_ORDER_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class Direction(str, Enum):
    """Sort direction exposed to federation pagination callers (ASC|DESC).

    Overrides an order profile's default direction; ``nulls`` follow the flip
    (see ``_apply_direction``). specs/014.
    """

    ASC = "ASC"
    DESC = "DESC"


@dataclass(frozen=True)
class PaginationRootMeta:
    """Runtime metadata attached to a generated ``page_by_<key>_in`` root.

    Written by ``_create_page_by_keys_in_query`` onto the function object as
    ``func._pagination_root``; read by sdl_generator / introspection /
    query_executor for SDL rendering, ``__schema`` introspection, and
    pagination-root routing. A frozen dataclass (not a bare dict) so the
    contract is typed and key typos surface at import rather than as a
    runtime ``KeyError`` at a consumer.
    """

    entity: type
    fk_field: str
    fk_type: type
    package_name: str
    order_enum: type
    page_capability: Any  # BatchPageCapability


@dataclass(frozen=True)
class OrderTerm:
    """One physical member-side ordering term."""

    field: Any
    direction: Literal["asc", "desc"] = "asc"
    nulls: Literal["first", "last"] | None = None


@dataclass(frozen=True)
class PageOrder:
    """A named semantic ordering profile exposed through federation capability."""

    terms: list[OrderTerm]
    description: str | None = None


@dataclass(frozen=True)
class BatchPageConfig:
    """Pagination capability for one entity batch key."""

    default_order: str
    orders: dict[str, PageOrder]


@dataclass(frozen=True)
class _ResolvedOrderTerm:
    field_name: str
    direction: Literal["asc", "desc"]
    nulls: Literal["first", "last"] | None


@dataclass(frozen=True)
class _ResolvedPageOrder:
    terms: tuple[_ResolvedOrderTerm, ...]
    description: str | None


class AutoQueryConfig:
    """Configuration for auto-generated standard queries.

    Pure policy: holds toggles and limits only. The async ``session_factory``
    used to execute ``by_id``/``by_filter`` is owned by the container
    (``Application`` / ``GraphQLHandler`` / MCP builder) and passed to
    :func:`add_standard_queries` separately — the config deliberately does not
    own a database connection. This lets one config be reused across apps that
    point at different databases.
    """

    def __init__(
        self,
        default_limit: int = 10,
        generate_by_id: bool = True,
        generate_by_filter: bool = True,
        enabled: bool = True,
        batch_keys: dict[str, list[str]] | None = None,
        batch_pages: dict[str, dict[str, BatchPageConfig]] | None = None,
    ):
        """Initialize the auto query configuration.

        Args:
            default_limit: Default limit for by_filter queries.
            generate_by_id: Whether to generate by_id query.
            generate_by_filter: Whether to generate by_filter query.
            enabled: Whether standard queries are enabled.
            batch_keys: Per-entity batch lookup fields for federation, mapping
                ``{EntityName: [field, ...]}``. For each field a
                ``by_<field>_in(values: list)`` batch query root is generated
                (``where field.in_(values)``). Generally useful beyond federation.
            batch_pages: Explicit member-side pagination capabilities, mapping
                ``{EntityName: {batch_field: BatchPageConfig(...)}}``. Each
                configured field generates ``page_by_<field>_in``.

        Note:
            ``session_factory`` was removed from this constructor — pass it to
            ``GraphQLHandler`` / ``Application`` instead. If you pass a callable
            positionally (old API), it is accepted with a DeprecationWarning and
            stored as ``_deprecated_session_factory`` for the container to pick up.
        """
        # ── Backward compat: detect old session_factory-as-first-arg ──────
        # Before the refactor, AutoQueryConfig(session_factory, ...) was the
        # signature. Now session_factory lives on the container. If someone
        # passes a non-int positionally, it's the old session_factory.
        self._deprecated_session_factory: Any = None
        if not isinstance(default_limit, int):
            import warnings

            warnings.warn(
                "AutoQueryConfig(session_factory) is deprecated — pass "
                "session_factory to GraphQLHandler / Application instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            self._deprecated_session_factory = default_limit
            default_limit = 10

        self.default_limit = default_limit
        self.generate_by_id = generate_by_id
        self.generate_by_filter = generate_by_filter
        self.enabled = enabled
        self.batch_keys = batch_keys or {}
        self.batch_pages = batch_pages or {}


async def _create_session_context(session_factory: Any) -> Any:
    """Create a session context, supporting sync and async factories."""
    session_context = session_factory()
    if inspect.isawaitable(session_context):
        session_context = await session_context
    return session_context


def _unwrap_optional_type(annotation: Any) -> Any:
    """Unwrap Optional[T] to T."""
    origin = get_origin(annotation)
    if origin in (types.UnionType, Union):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _get_primary_key_fields(entity: type[SQLModel]) -> list[tuple[str, Any]]:
    """Get primary key fields from an entity."""
    primary_keys: list[tuple[str, Any]] = []
    table = getattr(entity, "__table__", None)
    table_primary_keys = (
        {column.name for column in table.primary_key.columns}
        if table is not None and getattr(table, "primary_key", None) is not None
        else set()
    )
    fk_fields = get_fk_fields(entity)

    for field_name, field_info in entity.model_fields.items():
        has_primary_key = field_name in table_primary_keys
        has_foreign_key = field_name in fk_fields

        if hasattr(field_info, "primary_key"):
            if field_info.primary_key is True:
                has_primary_key = True

        if not has_primary_key and hasattr(field_info, "metadata"):
            for meta in field_info.metadata:
                if hasattr(meta, "primary_key") and meta.primary_key is True:
                    has_primary_key = True
                    break

        if has_primary_key and not has_foreign_key:
            primary_keys.append((field_name, _unwrap_optional_type(field_info.annotation)))

    return primary_keys


def _create_filter_input_type(entity: type[SQLModel]) -> type:
    """Create a filter input type from entity fields."""
    field_definitions: dict[str, tuple[type, Any]] = {}

    for field_name, field_info in entity.model_fields.items():
        if field_name.startswith("_") or field_name == "metadata":
            continue

        original_type = field_info.annotation
        field_type = original_type | None
        field_definitions[field_name] = (field_type, Field(default=None))

    return create_model(f"{entity.__name__}FilterInput", **field_definitions)


def _create_by_id_query(entity: type[SQLModel], session_factory: Any) -> Any:
    """Create by_id query method (no query_meta, DataLoader handles relationships)."""

    primary_keys = _get_primary_key_fields(entity)
    if len(primary_keys) != 1:
        return None

    primary_key_name, primary_key_type = primary_keys[0]

    @query
    async def by_id(cls, **kwargs: Any) -> Any:
        """Get entity by ID."""
        if primary_key_name not in kwargs:
            msg = f"Missing required primary key argument: {primary_key_name}"
            raise TypeError(msg)

        session_context = await _create_session_context(session_factory)
        async with session_context as session:
            stmt = select(cls).where(
                getattr(cls, primary_key_name) == kwargs[primary_key_name]
            )
            result = await session.exec(stmt)
            return result.first()

    func = by_id.__func__ if hasattr(by_id, "__func__") else by_id
    func.__annotations__[primary_key_name] = primary_key_type
    by_id.__annotations__["return"] = entity | None
    func.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                "cls",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
            inspect.Parameter(
                primary_key_name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=primary_key_type,
            ),
        ],
        return_annotation=entity | None,
    )

    return by_id


def _create_by_filter_query(
    entity: type[SQLModel],
    session_factory: Any,
    default_limit: int,
    filter_input_type: type,
) -> Any:
    """Create by_filter query method (no query_meta)."""

    @query
    async def by_filter(
        cls,
        filter: Any | None = None,
        limit: int = default_limit,
    ) -> Any:
        """Get entities by filter."""
        session_context = await _create_session_context(session_factory)
        async with session_context as session:
            stmt = select(cls)
            if filter is not None:
                if hasattr(filter, "model_dump"):
                    filter_values = filter.model_dump(exclude_none=True)
                elif isinstance(filter, dict):
                    filter_values = {
                        field_name: value
                        for field_name, value in filter.items()
                        if value is not None
                    }
                else:
                    filter_values = {
                        field_name: getattr(filter, field_name, None)
                        for field_name in filter_input_type.model_fields
                        if getattr(filter, field_name, None) is not None
                    }

                for field_name, value in filter_values.items():
                    if value is not None:
                        stmt = stmt.where(getattr(cls, field_name) == value)
            stmt = stmt.limit(limit)
            result = await session.exec(stmt)
            return list(result.all())

    func = by_filter.__func__ if hasattr(by_filter, "__func__") else by_filter
    func.__annotations__["filter"] = filter_input_type
    by_filter.__annotations__["return"] = list[entity]
    func._filter_input_type = filter_input_type

    return by_filter


def _create_by_keys_in_query(
    entity: type[SQLModel],
    session_factory: Any,
    field_name: str,
    field_type: type,
) -> Any:
    """Create a ``by_<field>_in`` batch query root (``where field.in_(values)``)."""

    arg_name = f"{field_name}_list"
    method_name = f"by_{field_name}_in"

    @query
    async def by_field_in(cls, **kwargs: Any) -> Any:
        """Batch-fetch entities where ``field`` is in the provided list."""
        if arg_name not in kwargs:
            msg = f"Missing required argument: {arg_name}"
            raise TypeError(msg)
        values = kwargs[arg_name]
        session_context = await _create_session_context(session_factory)
        async with session_context as session:
            stmt = select(cls).where(getattr(cls, field_name).in_(values))
            result = await session.exec(stmt)
            return list(result.all())

    func = by_field_in.__func__ if hasattr(by_field_in, "__func__") else by_field_in
    func.__annotations__[arg_name] = list[field_type]
    by_field_in.__annotations__["return"] = list[entity]
    func.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter("cls", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter(
                arg_name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=list[field_type],
            ),
        ],
        return_annotation=list[entity],
    )
    func.__name__ = method_name
    return by_field_in


def _create_page_by_keys_in_query(
    entity: type[SQLModel],
    session_factory: Any,
    field_name: str,
    field_type: type,
    page_config: BatchPageConfig,
) -> Any:
    """Create a ``page_by_<field>_in`` paginated batch root for federation.

    Per-key offset/limit pagination via ``ROW_NUMBER() OVER (PARTITION BY field)``:
    returns one ``{<field>, items, pagination}`` package per input key, so the
    mounting service can align by join key. ``has_more`` via peek-by-1;
    ``total_count`` via ``COUNT(*) OVER`` only when selected by the client.
    The executor injects the selected pagination field names as private runtime
    metadata; that metadata is not part of this root's public GraphQL signature.
    """
    from nexusx.federation.contract import (
        BatchPageCapability,
        PageOrderDescriptor,
    )

    arg_name = f"{field_name}_list"
    method_name = f"page_by_{field_name}_in"
    resolved_orders = _resolve_page_orders(entity, page_config)
    enum_name = f"{entity.__name__}{_pascal_case(field_name)}PageOrder"
    order_enum = Enum(enum_name, {name: name for name in resolved_orders})
    capability = BatchPageCapability(
        default_order=page_config.default_order,
        orders=[
            PageOrderDescriptor(name=name, description=order.description)
            for name, order in resolved_orders.items()
        ],
    )

    @query
    async def page_by_field_in(cls, **kwargs: Any) -> Any:
        """Per-key paginated batch fetch (federation pagination root)."""
        from collections import defaultdict

        from sqlalchemy import func, select

        from nexusx.loader.pagination import PageArgs, Pagination

        if arg_name not in kwargs:
            msg = f"Missing required argument: {arg_name}"
            raise TypeError(msg)
        values = list(kwargs[arg_name])
        page_args = PageArgs(
            limit=kwargs.get("limit"),
            offset=kwargs.get("offset", 0),
        )
        raw_order = kwargs["order"]
        order_name = raw_order.value if isinstance(raw_order, Enum) else raw_order
        if order_name not in resolved_orders:
            msg = (
                f"Unknown order profile {order_name!r} for "
                f"{cls.__name__}.{method_name}"
            )
            raise ValueError(msg)
        resolved_order = resolved_orders[order_name]
        # direction (specs/014): caller flips the profile's default direction;
        # nulls follow. effective_terms feed BOTH the window inner and the
        # outer order expressions so they stay consistent after the flip.
        effective_terms = _apply_direction(
            resolved_order.terms, kwargs.get("direction")
        )
        pagination_selection = kwargs.get("__nexusx_pagination_selection")
        # Direct Python callers do not provide execution metadata, so preserve
        # the historical full Pagination result for that path.
        want_total_count = (
            pagination_selection is None
            or "total_count" in pagination_selection
        )
        effective_limit = page_args.effective_limit

        if not values:
            return []

        async with session_factory() as session:
            fk_col = getattr(cls, field_name)
            window_order = _build_order_expressions(cls, effective_terms)

            rn_label = "_nx_rn"
            tc_label = "_nx_tc"
            row_num_col = func.row_number().over(
                partition_by=fk_col,
                order_by=window_order,
            ).label(rn_label)
            inner_columns = [cls, row_num_col]
            if want_total_count:
                inner_columns.append(
                    func.count().over(partition_by=fk_col).label(tc_label)
                )
            inner = select(*inner_columns).where(fk_col.in_(values))
            subq = inner.subquery()

            rn_col = subq.c[rn_label]
            fk_col_sub = subq.c[field_name]
            outer_order = _build_order_expressions(subq.c, effective_terms)

            start = page_args.offset + 1
            end = page_args.offset + effective_limit + 1  # peek-by-1
            outer = (
                select(subq)
                .where(rn_col.between(start, end))
                .order_by(fk_col_sub, *outer_order)
            )
            rows = (await session.exec(outer)).all()

            grouped: dict[Any, list[Any]] = defaultdict(list)
            total_counts: dict[Any, int] = {}
            entity_fields = set(cls.model_fields.keys())
            for row in rows:
                mapping = row._mapping
                fk_val = mapping[field_name]
                grouped[fk_val].append(mapping)
                if want_total_count:
                    total_counts[fk_val] = mapping[tc_label]

            # Keys whose offset is beyond their total (no rows in the window)
            # still need a total_count entry.
            missing = (
                [v for v in values if v not in total_counts]
                if want_total_count
                else []
            )
            if missing:
                count_q = (
                    select(fk_col, func.count().label(tc_label))
                    .where(fk_col.in_(missing))
                    .group_by(fk_col)
                )
                for row in (await session.exec(count_q)).all():
                    total_counts[row[0]] = row[1]

            packages: list[dict[str, Any]] = []
            for v in values:
                page_rows = grouped.get(v, [])[:effective_limit]
                items = [
                    cls(**{k: r[k] for k in entity_fields if k in r})
                    for r in page_rows
                ]
                # specs/021 GAP E: limit=0 must not claim a next page — the
                # window peek-by-1 still fetches rn=offset+1, which would make
                # ``len > effective_limit`` true with empty items.
                has_more = (
                    effective_limit > 0
                    and len(grouped.get(v, [])) > effective_limit
                )
                pagination = Pagination(has_more=has_more)
                if want_total_count:
                    pagination.total_count = total_counts.get(v, 0)
                packages.append({
                    field_name: v,
                    "items": items,
                    "pagination": pagination,
                })
            return packages

    func_obj = (
        page_by_field_in.__func__
        if hasattr(page_by_field_in, "__func__")
        else page_by_field_in
    )
    func_obj.__annotations__[arg_name] = list[field_type]
    func_obj.__annotations__["limit"] = int | None
    func_obj.__annotations__["offset"] = int
    func_obj.__annotations__["order"] = order_enum
    func_obj.__annotations__["direction"] = Direction
    page_by_field_in.__annotations__["return"] = list[dict]
    func_obj.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter("cls", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter(
                arg_name, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=list[field_type],
            ),
            inspect.Parameter(
                "order", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=order_enum,
            ),
            inspect.Parameter(
                "direction", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None, annotation=Direction,
            ),
            inspect.Parameter(
                "limit", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None, annotation=int | None,
            ),
            inspect.Parameter(
                "offset", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=0, annotation=int,
            ),
        ],
        return_annotation=list[dict],
    )
    func_obj.__name__ = method_name
    package_name = f"{entity.__name__}{_pascal_case(field_name)}PagePackage"
    func_obj._pagination_root = PaginationRootMeta(
        entity=entity,
        fk_field=field_name,
        fk_type=field_type,
        package_name=package_name,
        order_enum=order_enum,
        page_capability=capability,
    )
    return page_by_field_in


def _pascal_case(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in value.split("_") if part)


def _column_name_from_term(entity: type[SQLModel], field: Any) -> str:
    if isinstance(field, str):
        return field
    field_name = getattr(field, "key", None)
    owner = getattr(field, "class_", None)
    if not isinstance(field_name, str) or owner is not entity:
        raise ValueError(
            f"OrderTerm.field for {entity.__name__} must be a column name or "
            f"a direct {entity.__name__} column attribute"
        )
    return field_name


def _resolve_page_orders(
    entity: type[SQLModel],
    config: BatchPageConfig,
) -> dict[str, _ResolvedPageOrder]:
    from sqlalchemy import JSON, LargeBinary
    from sqlalchemy import inspect as sa_inspect

    if not config.orders:
        raise ValueError(
            f"BatchPageConfig for {entity.__name__} must define at least one order"
        )
    if config.default_order not in config.orders:
        raise ValueError(
            f"default_order {config.default_order!r} is not defined for "
            f"{entity.__name__}"
        )

    mapper = sa_inspect(entity)
    columns = {column.key: column for column in mapper.columns}
    primary_keys = [column.key for column in mapper.primary_key]
    resolved: dict[str, _ResolvedPageOrder] = {}
    for name, order in config.orders.items():
        if not _ORDER_NAME_RE.fullmatch(name) or name.startswith("__"):
            raise ValueError(
                f"Order profile {name!r} on {entity.__name__} must be a "
                "GraphQL enum-safe uppercase name"
            )
        if not isinstance(order, PageOrder):
            raise TypeError(
                f"Order profile {name!r} on {entity.__name__} must be PageOrder"
            )
        if not order.terms:
            raise ValueError(
                f"Order profile {name!r} on {entity.__name__} cannot be empty"
            )
        if len(order.terms) != 1:
            raise ValueError(
                f"Order profile {name!r} on {entity.__name__} must have exactly "
                f"one term (single-column sort, specs/014), "
                f"got {len(order.terms)}"
            )

        terms: list[_ResolvedOrderTerm] = []
        used_fields: set[str] = set()
        for term in order.terms:
            if not isinstance(term, OrderTerm):
                raise TypeError(
                    f"Order profile {name!r} on {entity.__name__} contains a "
                    "non-OrderTerm value"
                )
            field_name = _column_name_from_term(entity, term.field)
            column = columns.get(field_name)
            if column is None:
                raise ValueError(
                    f"Order field {field_name!r} is not a SQL column on "
                    f"{entity.__name__}"
                )
            if isinstance(column.type, (JSON, LargeBinary)):
                raise ValueError(
                    f"Order field {entity.__name__}.{field_name} uses unsupported "
                    f"column type {type(column.type).__name__}"
                )
            if term.direction not in ("asc", "desc"):
                raise ValueError(
                    f"Order direction for {entity.__name__}.{field_name} must be "
                    "'asc' or 'desc'"
                )
            if term.nulls not in (None, "first", "last"):
                raise ValueError(
                    f"Order nulls for {entity.__name__}.{field_name} must be "
                    "'first' or 'last'"
                )
            if column.nullable and term.nulls is None:
                raise ValueError(
                    f"Nullable order field {entity.__name__}.{field_name} must "
                    "declare nulls='first' or nulls='last'"
                )
            if field_name in used_fields:
                raise ValueError(
                    f"Order profile {name!r} repeats field {field_name!r}"
                )
            used_fields.add(field_name)
            terms.append(
                _ResolvedOrderTerm(field_name, term.direction, term.nulls)
            )

        tie_direction = terms[-1].direction
        for pk_name in primary_keys:
            if pk_name not in used_fields:
                terms.append(_ResolvedOrderTerm(pk_name, tie_direction, None))
        resolved[name] = _ResolvedPageOrder(tuple(terms), order.description)
    return resolved


def _build_order_expressions(
    source: Any,
    terms: tuple[_ResolvedOrderTerm, ...],
) -> list[Any]:
    expressions: list[Any] = []
    for term in terms:
        column = getattr(source, term.field_name)
        expression = (
            column.desc() if term.direction == "desc" else column.asc()
        )
        if term.nulls == "first":
            expression = expression.nulls_first()
        elif term.nulls == "last":
            expression = expression.nulls_last()
        expressions.append(expression)
    return expressions


def _apply_direction(
    terms: tuple[_ResolvedOrderTerm, ...], raw_direction: Any
) -> tuple[_ResolvedOrderTerm, ...]:
    """Apply a caller-supplied direction to a profile's resolved terms.

    ``None`` direction ⇒ profile default (no flip). Otherwise override each
    term's direction; ``nulls`` flip (first↔last) only on terms whose direction
    actually changes; terms already matching the requested direction stay. The
    result feeds both the window inner and the outer order expressions so they
    remain consistent. specs/014.
    """
    if raw_direction is None:
        return terms
    direction = (
        raw_direction.value if isinstance(raw_direction, Enum) else raw_direction
    )
    if isinstance(direction, str):
        direction = direction.lower()
    return tuple(
        t
        if direction == t.direction
        else _ResolvedOrderTerm(
            t.field_name,
            direction,
            None if t.nulls is None else ("first" if t.nulls == "last" else "last"),
        )
        for t in terms
    )


def add_standard_queries(
    entities: list[type[SQLModel]],
    config: AutoQueryConfig,
    session_factory: Any,
) -> None:
    """Add standard queries (by_id, by_filter) to entities.

    Args:
        entities: List of SQLModel entity classes.
        config: AutoQueryConfig (policy only — toggles and limits).
        session_factory: Async session factory from the owning container
            (Application / GraphQLHandler / MCP builder). Used by the generated
            by_id / by_filter to actually query the database; the config no
            longer carries it.
    """
    if not config.enabled:
        return

    for entity in entities:
        if config.generate_by_id and not hasattr(entity, "by_id"):
            by_id_method = _create_by_id_query(entity, session_factory)
            if by_id_method is not None:
                entity.by_id = by_id_method

        if config.generate_by_filter and not hasattr(entity, "by_filter"):
            filter_input_type = _create_filter_input_type(entity)
            by_filter_method = _create_by_filter_query(
                entity,
                session_factory,
                config.default_limit,
                filter_input_type,
            )
            entity.by_filter = by_filter_method

        # Batch lookup roots (by_<key>_in) — used by federation RemoteLoader.
        for field_name in config.batch_keys.get(entity.__name__, []):
            method_name = f"by_{field_name}_in"
            if field_name not in entity.model_fields:
                msg = (
                    f"AutoQueryConfig.batch_keys field {field_name!r} is not a "
                    f"column on {entity.__name__}"
                )
                raise ValueError(msg)
            field_type = _unwrap_optional_type(entity.model_fields[field_name].annotation)
            if not hasattr(entity, method_name):
                setattr(
                    entity,
                    method_name,
                    _create_by_keys_in_query(entity, session_factory, field_name, field_type),
                )

        # Explicit member-side pagination capabilities.
        for field_name, page_config in config.batch_pages.get(
            entity.__name__, {}
        ).items():
            page_method_name = f"page_by_{field_name}_in"
            if field_name not in entity.model_fields:
                msg = (
                    f"AutoQueryConfig.batch_pages field {field_name!r} is not a "
                    f"column on {entity.__name__}"
                )
                raise ValueError(msg)
            field_type = _unwrap_optional_type(
                entity.model_fields[field_name].annotation
            )
            if not hasattr(entity, page_method_name):
                setattr(
                    entity,
                    page_method_name,
                    _create_page_by_keys_in_query(
                        entity,
                        session_factory,
                        field_name,
                        field_type,
                        page_config,
                    ),
                )


# ──────────────────────────────────────────────────────────────────────
# specs/016 — DTO batch roots (γ-path member public DTO 取数入口)
# ──────────────────────────────────────────────────────────────────────


def _create_dto_by_keys_in_query(
    dto_cls: type,
    base_entity: type[SQLModel],
    join_key: str,
    er_manager: Any,
    session_factory: Any,
    page_orders_resolved: dict | None = None,
    default_order: str | None = None,
) -> Any:
    """Create a ``by_<join_key>_in(values) -> list[dict]`` DTO batch root.

    Unlike ``_create_by_keys_in_query`` (entity batch root via raw SQL), this
    returns a RESOLVED DTO tree: SQL-fetch entities by join_key → build DTO
    instances from the subset fields → ``er.create_resolver().resolve()`` runs
    every ``resolve_*``/``post_*`` (incl. cross-service out-edges, since the
    member is itself a federation mounter) → ``model_dump(mode="json")``.

    The member Resolver is what makes the DTO self-contained: business logic
    (discounts, aggregates, transitive ``author → users``) executes here, on the
    data owner. The mounter receives finished DTO trees, never raw rows.

    Registered as a plain async function (NOT a ``@query``) on
    ``er_manager._dto_batch_roots`` — served by the dedicated DTO batch HTTP
    endpoint, not the β GraphQL surface (FR-008: β 不动).
    """
    subset_fields = list(getattr(dto_cls, "__subset_fields__", []) or [])

    async def by_key_in(
        values: list[Any],
        order: str | None = None,
        direction: Any = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        if not values:
            return []
        if limit == 0:
            return []
        from sqlalchemy import func

        # specs/021 F2: fail-fast validation, aligned with β's PageArgs — a
        # negative limit/offset used to silently produce an empty window.
        from nexusx.loader.pagination import PageArgs

        page_args = PageArgs(limit=limit, offset=offset)
        if direction is not None and direction not in ("asc", "desc"):
            raise ValueError(
                f"Invalid direction {direction!r} for "
                f"{dto_cls.__name__}.{join_key}"
            )

        # Resolve the effective order profile: caller order → default → None.
        # specs/021 F3: an unknown profile fails fast (β's page_by_field_in
        # raises at the same spot) instead of silently degrading to a full,
        # unordered fetch.
        order_terms = None
        if page_orders_resolved is not None:
            order_name = order or default_order
            if order_name is not None:
                if order_name not in page_orders_resolved:
                    raise ValueError(
                        f"Unknown order profile {order_name!r} for "
                        f"DTO {dto_cls.__name__}.{join_key}"
                    )
                order_terms = _apply_direction(
                    page_orders_resolved[order_name].terms, direction,
                )

        session_context = await _create_session_context(session_factory)
        async with session_context as session:
            fk_col = getattr(base_entity, join_key)
            # Per-parent top-N (specs/016 Phase 2): ROW_NUMBER OVER (PARTITION
            # BY join_key ORDER BY <order>) keeps the slice in SQL — before DTO
            # build + Resolver — so the member never fetches/resolves the full
            # collection (no wasted cross-service hops). Mirrors PO2M
            # (factories.py:397-436). specs/021 F1: an order profile alone is
            # enough to slice — a missing limit uses the default page size
            # (aligned with β, where the member's PageArgs default applies);
            # previously `Paged(order=...)` without limit silently degraded to
            # a full, UNORDERED fetch. Falls back to full fetch only when
            # there's no order profile at all (un-paged batch roots).
            if order_terms is not None:
                effective_limit = page_args.effective_limit
                rn_label = "_nx_rn"
                inner_order = _build_order_expressions(base_entity, order_terms)
                row_num_col = func.row_number().over(
                    partition_by=fk_col, order_by=inner_order,
                ).label(rn_label)
                inner = select(base_entity, row_num_col).where(fk_col.in_(values))
                subq = inner.subquery()
                rn_col = subq.c[rn_label]
                fk_col_sub = subq.c[join_key]
                # rn BETWEEN offset+1 AND offset+effective_limit (offset=0 →
                # top-N).
                start = offset + 1
                end = offset + effective_limit
                outer = (
                    select(subq)
                    .where(rn_col.between(start, end))
                    .order_by(fk_col_sub, *_build_order_expressions(subq.c, order_terms))
                )
                # session.execute (not .exec): SQLModel's .exec yields the
                # first column's scalars for select(subq); .execute returns
                # Rows with ._mapping. Suppress the "use exec" hint.
                import warnings as _warnings

                with _warnings.catch_warnings():
                    _warnings.simplefilter("ignore", DeprecationWarning)
                    rows = (await session.execute(outer)).all()
                entity_fields = set(base_entity.model_fields.keys())
                entities = [
                    base_entity(**{
                        k: r._mapping[k] for k in entity_fields if k in r._mapping
                    })
                    for r in rows
                ]
            else:
                stmt = select(base_entity).where(fk_col.in_(values))
                entities = list((await session.exec(stmt)).all())
        if not entities:
            return []
        # Build DTO instances from entity-sourced subset fields; Resolver-computed
        # fields stay at their default and are filled by resolve().
        dtos = [
            dto_cls(**{f: getattr(e, f, None) for f in subset_fields})
            for e in entities
        ]
        ResolverCls = er_manager.create_resolver()
        resolved = await ResolverCls().resolve(dtos)
        rows: list[dict] = []
        for dto in resolved:
            row = dto.model_dump(mode="json")
            # The federation join key is transport metadata. It must remain on
            # the wire even when the DTO hides an auto-included FK from normal
            # business serialization.
            row[join_key] = getattr(dto, join_key)
            rows.append(row)
        return rows

    by_key_in.__name__ = f"by_{join_key}_in"
    return by_key_in


def add_dto_batch_roots(er_manager: Any) -> None:
    """Register a DTO batch root for each federation-public DTO on the member.

    For every ``er_manager.get_public_dtos()`` entry (SubsetConfig
    ``federation_public=True``), read its join_key + base entity, fail-fast
    validate the join_key is a column on the base entity, and store
    ``(by_<join_key>_in, join_key)`` under ``er_manager._dto_batch_roots[dto_name]``.

    Called from ``GraphQLHandler.__init__`` (symmetric to ``add_standard_queries``)
    so the batch roots exist at app startup. They're served at query time by the
    ``POST /nexusx/dto-batch`` endpoint, one HTTP call per mounted DTO per γ
    traversal (N+1-proof via DataLoader batching on the mounter side).

    Idempotent / additive: no-op when the member declares no public DTOs (β
    services are unaffected).
    """
    from nexusx.federation.introspect import _type_expr
    from nexusx.federation.manager import _SUPPORTED_JOIN_TYPES, _normalize_join_type
    from nexusx.subset import get_subset_source

    session_factory = er_manager._session_factory
    batch_roots: dict[str, tuple[Any, str]] = {}
    for dto_cls in er_manager.get_public_dtos():
        join_key = getattr(dto_cls, "__federation_join_key__", None)
        if not join_key:
            # get_public_dtos() filters by __federation_public__; a public DTO
            # without a join_key was already rejected at SubsetMeta validation.
            continue
        base_entity = get_subset_source(dto_cls)
        if base_entity is None:
            raise ValueError(
                f"{dto_cls.__name__} is federation-public but has no subset "
                f"source entity; cannot generate a DTO batch root."
            )
        if join_key not in base_entity.model_fields:
            raise ValueError(
                f"{dto_cls.__name__} join_key {join_key!r} is not a column on "
                f"base entity {base_entity.__name__}; cannot batch-fetch by it."
            )
        # Join-key type gate (specs/016, symmetric to β's _check_join_contract):
        # DTO federation ships keys over JSON and aligns them back via
        # _normalize_join_key (UUID→str). A key type outside _SUPPORTED_JOIN_TYPES
        # would either fail json.dumps (UUID without normalization) or silently
        # miss its bucket (Decimal serializes to str on the response side but
        # isn't normalized on the lookup side). Reject at startup on the member
        # — it owns the base-entity column type, so this is the earliest fail-fast.
        join_type_name = _normalize_join_type(
            _type_expr(base_entity.model_fields[join_key].annotation)
        )
        if join_type_name is None or join_type_name not in _SUPPORTED_JOIN_TYPES:
            supported = ", ".join(sorted(_SUPPORTED_JOIN_TYPES))
            raise ValueError(
                f"{dto_cls.__name__} federation_join_key {join_key!r} has "
                f"unsupported type {join_type_name!r} on {base_entity.__name__}; "
                f"DTO federation serializes keys over JSON — supported join-key "
                f"types: {supported}."
            )
        # specs/016 Phase 2: resolve a DTO-level __pagination_orders__
        # (BatchPageConfig) into physical OrderTerms, validated against the
        # base entity's columns (fail-fast at startup — same gate as entity
        # __pagination_orders__). Fed to the batch root for per-parent top-N
        # when the mounter sends order+limit.
        cfg = getattr(dto_cls, "__pagination_orders__", None)
        page_orders_resolved = None
        default_order = None
        if cfg is not None:
            page_orders_resolved = _resolve_page_orders(base_entity, cfg)
            default_order = cfg.default_order
        batch_roots[dto_cls.__name__] = (
            _create_dto_by_keys_in_query(
                dto_cls, base_entity, join_key, er_manager, session_factory,
                page_orders_resolved=page_orders_resolved,
                default_order=default_order,
            ),
            join_key,
        )
    er_manager._dto_batch_roots = batch_roots
