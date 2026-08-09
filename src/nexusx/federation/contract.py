"""ER fragment wire types — the federation introspection payload.

Serialized by the member-side ER introspection endpoint and consumed by the
mounter's ``FederatedTypeRegistry``. Mirrors ``RelationshipInfo`` field
semantics; loader callables are deliberately NOT serialized (they are code,
not data). This is the federation composition source — same source as
Voyager/executor, not GraphQL SDL.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class FieldDescriptor(BaseModel):
    """A scalar field on an entity."""

    name: str
    type_name: str


class PageOrderDescriptor(BaseModel):
    """One semantic order profile exposed by a member."""

    name: str
    description: str | None = None


class BatchPageCapability(BaseModel):
    """Member-owned pagination protocol and semantic order profiles."""

    protocol: Literal["offset-v1"] = "offset-v1"
    default_order: str
    orders: list[PageOrderDescriptor]


class BatchRoot(BaseModel):
    """A generated federation batch query root and its argument contract.

    Carrying the argument name (and type) makes the federation contract
    self-describing: the mounter sends the argument name the member actually
    declared, instead of assuming the ``<key>_list`` convention — so a member
    that renamed the argument fails fast at ``federate()`` rather than at query
    time. ``arg_name``/``arg_type`` are ``""`` when the signature could not be
    introspected (the mounter rejects such roots).
    """

    name: str  # e.g. "by_product_id_in" or "page_by_product_id_in"
    arg_name: str = ""  # e.g. "product_id_list"
    arg_type: str = ""  # lossless type expr, e.g. "list[UUID]"
    page: BatchPageCapability | None = None


class RelDescriptor(BaseModel):
    """One relationship on an entity (local or remote)."""

    name: str
    direction: str
    fk_field: str
    target_typename: str
    is_list: bool = False
    pagination: bool = False
    # Remote relationships carry the owning service + endpoint so the mounter
    # can discover the reachable subgraph transitively (FR-005).
    target_service: str | None = None
    target_endpoint: str | None = None


class EntityFragment(BaseModel):
    """One entity type as exposed by a member's ER introspection."""

    typename: str
    pk_field: str | None = None  # primary key field name (for remote loader join_remote)
    scalar_fields: list[FieldDescriptor] = Field(default_factory=list)
    relationships: list[RelDescriptor] = Field(default_factory=list)
    # Generated batch query roots on this type, with their argument contract.
    # Plain strings are coerced to a
    # BatchRoot whose arg_name is derived from the by_<key>_in convention, so
    # hand-built/test fragments that pass ["by_id_in"] keep working.
    batch_roots: list[BatchRoot] = Field(default_factory=list)

    @field_validator("batch_roots", mode="before")
    @classmethod
    def _coerce_batch_roots(cls, v):
        if not isinstance(v, (list, tuple)):
            return v
        coerced = []
        for item in v:
            if isinstance(item, str):
                m = re.match(r"^by_(.+)_in$", item)
                arg_name = f"{m.group(1)}_list" if m else ""
                coerced.append({"name": item, "arg_name": arg_name, "arg_type": ""})
            else:
                coerced.append(item)
        return coerced


class DTOFragment(BaseModel):
    """One public DTO type as exposed by a member's DTO introspection.

    Symmetric to ``EntityFragment`` but for UseCase-layer DTOs (a subset of
    an entity plus Resolver-computed fields). The mounter materializes this
    into a local DTO class (``create_model``) and fetches DTO trees through
    ``batch_root`` — the same federation composition mechanism as entities,
    with the composition source switched from ER rows to Resolver-produced
    DTO trees (γ path).
    """

    name: str  # DTO class name (__name__)
    base_entity: str  # source entity name (_subset_registry[DTO].__name__)
    # All DTO fields + types (skeleton + PK + Resolver-computed), mirroring
    # EntityFragment.scalar_fields. DTOs have no ORM column/relationship split,
    # so every model_fields entry is a scalar from the federation standpoint.
    scalar_fields: list[FieldDescriptor] = Field(default_factory=list)
    join_key: str  # federation join key (derived from entity __federation_keys__)
    batch_root: BatchRoot  # generated DTO batch root (by_<join_key>_in DTO variant)
    # Cross-service out-edges on the DTO (__relationships__).
    remote_refs: list[RelDescriptor] = Field(default_factory=list)


class ERIntrospectionResponse(BaseModel):
    """Full ER introspection payload for one member service."""

    service_name: str
    entities: list[EntityFragment] = Field(default_factory=list)


class DTOIntrospectionResponse(BaseModel):
    """Full DTO introspection payload for one member service.

    Served by the independent DTO introspection endpoint (β ER introspection
    is untouched). Each entry is a federation-public DTO the member exposes.
    """

    service_name: str
    dtos: list[DTOFragment] = Field(default_factory=list)
