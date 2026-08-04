"""Pagination types for DataLoader-based relationship resolution.

Adapted from pydantic-resolve's graphql.pagination.types module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, create_model


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
    """Declarative top-N marker for a DefineSubset DTO field.

    Attached via ``Annotated[list[Target], Paged(...)]`` on a DefineSubset
    field whose name matches a source-entity relationship. It tells the
    Resolver to fetch a limited, ordered slice (top-N) instead of the full
    list — the typical "thread.comments top 10" shape.

    The order profiles AND the page_loader itself come from the SOURCE
    ENTITY's ``__pagination_orders__`` declaration (specs/015): Paged only
    sets the limit and selects which declared order to use. Physical ORDER BY
    terms stay on the data-owning entity — the same split as γ remote
    federation (orders sourced from the member), so the DTO never pins
    physical sort terms it doesn't own.

    limit: max items per parent (the top-N).
    default_order: name of the source entity's order profile to use; None ⇒
        the entity's declared default_order.
    """

    limit: int
    default_order: str | None = None

    def __post_init__(self) -> None:
        if self.limit < 0:
            raise ValueError(f"Paged.limit must be >= 0, got {self.limit}")


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

    config = {}
    if getattr(item_type, "model_config", {}).get("from_attributes"):
        config = {"from_attributes": True}

    return create_model(model_name, **config, **fields)
