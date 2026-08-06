"""Pagination types for DataLoader-based relationship resolution.

Adapted from pydantic-resolve's graphql.pagination.types module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model


class Pagination(BaseModel):
    """Pagination metadata returned alongside items."""

    has_more: bool = False
    total_count: int | None = None


@dataclass(frozen=True)
class PageArgs:
    """Pagination parameters extracted from GraphQL field arguments."""

    limit: int | None = None
    offset: int = 0
    default_page_size: int = 20
    max_page_size: int = 100

    def __post_init__(self) -> None:
        """Validate pagination arguments early."""
        if self.limit is not None and self.limit < 0:
            raise ValueError("limit must be greater than or equal to 0")
        if self.offset < 0:
            raise ValueError("offset must be greater than or equal to 0")
        if self.default_page_size <= 0:
            raise ValueError("default_page_size must be greater than 0")
        if self.max_page_size <= 0:
            raise ValueError("max_page_size must be greater than 0")

    @property
    def effective_limit(self) -> int:
        """Resolve the effective page size."""
        if self.limit is not None:
            return min(self.limit, self.max_page_size)
        return self.default_page_size


@dataclass(frozen=True)
class PageLoadCommand:
    """Key sent to a paginated DataLoader.

    The loader's batch_load_fn receives a list of these commands.
    All commands in a single batch share the same PageArgs / order / direction
    (guaranteed by GraphQL query structure). ``order``/``direction`` are set
    only for relationships with a ``page_capability`` (specs/015 local order).
    """

    fk_value: Any
    page_args: PageArgs
    order: str | None = None
    direction: Any = None


@dataclass(frozen=True)
class Paged:
    """Page params for an ER-relationship DTO field — declarative default
    (``Annotated[list[Target], Paged(...)]`` on the field) AND the merged
    result (Paged default + caller context override).

    All four params map 1:1 to ``PageLoadCommand`` → PO2M (limit/offset via
    PageArgs → ROW_NUMBER BETWEEN; order → ``page_orders_resolved[order]``;
    direction → ``_apply_direction``). ``order=None`` falls back to the source
    entity's ``__pagination_orders__`` default_order; ``direction=None`` to
    the order profile's default direction.

    ``params_key()`` gives a hashable cache key for per-params split
    (different merged params → different loader instance → different batch).
    """

    limit: int | None = None
    offset: int = 0
    order: str | None = None
    direction: str | None = None

    def params_key(self) -> tuple:
        return (self.limit, self.offset, self.order, self.direction)


@dataclass(frozen=True)
class _PagedOverride:
    """Caller pagination values where ``None`` means the arg was omitted."""

    limit: int | None = None
    offset: int | None = None
    order: str | None = None
    direction: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> _PagedOverride | None:
        """Build from a raw args/context dict (specs/021 P1-8).

        Shared by the two caller-parameter readers (entity-first gql
        ``field_sel.arguments`` and γ Resolver ``context``). Omitted keys stay
        ``None`` so callers can distinguish "not provided" from explicit zero
        values (e.g. ``offset=0``); enum values are unwrapped (``.value``).
        Non-wire values (anything that isn't int/str/None — e.g. graphql's
        ``Undefined`` for unresolved query variables) are treated as omitted,
        so a stray value can never reach ``PageArgs`` and crash the query.
        Returns None when nothing is set (→ no override).
        """

        def _clean(v: Any) -> Any:
            if v is None or isinstance(v, (int, str)):
                return v
            return None

        order = raw.get("order")
        direction = raw.get("direction")
        limit = raw.get("limit")
        offset = raw.get("offset") if "offset" in raw else None
        order = order.value if hasattr(order, "value") else order
        direction = direction.value if hasattr(direction, "value") else direction
        limit, offset, order, direction = (
            _clean(limit), _clean(offset), _clean(order), _clean(direction),
        )
        if limit is None and offset is None and order is None and direction is None:
            return None
        return cls(limit=limit, offset=offset, order=order, direction=direction)


def _build_pagination_model(pagination_selection: set[str]) -> type[BaseModel]:
    """Create a Pagination model containing only the selected fields."""
    fields = {}
    if "has_more" in pagination_selection:
        fields["has_more"] = (bool, False)
    if "total_count" in pagination_selection:
        fields["total_count"] = (int | None, None)

    if not fields:
        return Pagination

    return create_model("Pagination", **fields)


def create_result_type(
    item_type: type,
    pagination_selection: set[str] | None = None,
) -> type[BaseModel]:
    """Create a Result type parameterized by item_type.

    Produces a model with:
        items: list[item_type]
        pagination: Pagination (if pagination_selection provided)

    Args:
        item_type: The model type for list items.
        pagination_selection: Set of selected pagination field names
            (e.g. {'has_more', 'total_count'}).  When provided, the
            generated Pagination model only contains the requested fields.
            When None, the Result model only contains items (no pagination).
    """
    model_name = f"{getattr(item_type, '__name__', 'Item')}Result"

    fields: dict[str, Any] = {
        "items": (list[item_type], Field(default_factory=list)),
    }

    if pagination_selection:
        pag_model = _build_pagination_model(pagination_selection)
        fields["pagination"] = (pag_model, Field(default_factory=pag_model))

    # NOTE: ``from_attributes`` must go through ``__config__`` — spreading it
    # via ``**config`` would register it as a *field* named "from_attributes"
    # with annotation ``True`` (pydantic then fails to build its schema).
    # specs/021: the branch became reachable once build_model started emitting
    # nested models with from_attributes=True (entity-first's old builder never
    # set it, which hid this bug). Only set the config when the item type
    # carries it — absence keeps the pre-existing behavior (and the
    # ``test_no_from_attributes`` contract).
    if getattr(item_type, "model_config", {}).get("from_attributes"):
        return create_model(
            model_name,
            __config__=ConfigDict(from_attributes=True),
            **fields,
        )

    return create_model(model_name, **fields)
