"""Regression tests for federation findings from the branch review."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from pydantic import create_model
from sqlmodel import Field, SQLModel

from nexusx import GraphQLHandler
from nexusx.federation import (
    FederationTransportError,
    RemoteRelationship,
    RemoteService,
)
from nexusx.federation.contract import (
    BatchRoot,
    EntityFragment,
    ERIntrospectionResponse,
    FieldDescriptor,
)
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import serialize_er_introspection
from nexusx.federation.manager import FederationError, _check_join_contract
from nexusx.federation.registry import FederatedTypeRegistry
from nexusx.federation.remote_loader import (
    RemoteQueryError,
    build_gql_query,
    create_remote_loader,
    set_remote_selection,
)
from nexusx.loader.registry import ErManager
from nexusx.query_parser import FieldSelection
from nexusx.sdl_generator import SDLGenerator

review_remote = RemoteService("review_remote", url="http://review-remote")


class ReviewMissingLocalJoinProduct(SQLModel, table=True):
    __tablename__ = "review_missing_local_join_product"

    id: int | None = Field(default=None, primary_key=True)
    __relationships__ = [
        RemoteRelationship(
            fk="missing_product_key",
            target=review_remote.ReviewRemoteRow,
            name="review",
            join_remote="product_id",
        )
    ]


class ReviewMismatchedJoinProduct(SQLModel, table=True):
    __tablename__ = "review_mismatched_join_product"

    id: int | None = Field(default=None, primary_key=True)
    __relationships__ = [
        RemoteRelationship(
            fk="id",
            target=review_remote.StringKeyRemoteRow,
            name="review",
            join_remote="product_id",
        )
    ]


class ReviewDuplicateRelationshipProduct(SQLModel, table=True):
    __tablename__ = "review_duplicate_relationship_product"

    id: int | None = Field(default=None, primary_key=True)
    __relationships__ = [
        RemoteRelationship(
            fk="id",
            target=review_remote.ReviewRemoteRow,
            name="duplicate",
            join_remote="product_id",
        ),
        RemoteRelationship(
            fk="id",
            target=review_remote.CommentRemoteRow,
            name="duplicate",
            join_remote="product_id",
        ),
    ]


class ReviewRequiredSchemaRow(SQLModel, table=True):
    __tablename__ = "review_required_schema_row"

    id: int | None = Field(default=None, primary_key=True)
    title: str


class ReviewRetryProduct(SQLModel, table=True):
    __tablename__ = "review_retry_product"

    id: int | None = Field(default=None, primary_key=True)
    __relationships__ = [
        RemoteRelationship(
            fk="id",
            target=review_remote.RetryRemoteRow,
            name="review",
            join_remote="product_id",
        )
    ]


class ReviewLifecycleBase(SQLModel):
    pass


class ReviewLifecycleRow(ReviewLifecycleBase, table=True):
    __tablename__ = "review_lifecycle_row"

    id: int | None = Field(default=None, primary_key=True)


def _entity(
    typename: str,
    *,
    product_id_type: str = "int",
) -> EntityFragment:
    return EntityFragment(
        typename=typename,
        scalar_fields=[
            FieldDescriptor(name="id", type_name="int"),
            FieldDescriptor(name="product_id", type_name=product_id_type),
        ],
        batch_roots=[
            BatchRoot(
                name="by_product_id_in",
                arg_name="product_id_list",
                arg_type=f"list[{product_id_type}]",
            )
        ],
    )


class _IntrospectionTransport:
    def __init__(self, *entities: EntityFragment) -> None:
        self._payload = ERIntrospectionResponse(
            service_name="review_remote",
            entities=list(entities),
        ).model_dump()

    async def get_json(self, url: str) -> dict:
        return self._payload

    async def post_json(self, url: str, body: dict) -> dict:
        return {"data": {}}

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_initialize_rejects_missing_local_join_field():
    er = ErManager(
        entities=[ReviewMissingLocalJoinProduct],
        session_factory=lambda: None,
    )
    transport = _IntrospectionTransport(_entity("ReviewRemoteRow"))

    with pytest.raises(FederationError, match=r"missing_product_key.*local"):
        await er.initialize(transport=transport)


@pytest.mark.asyncio
async def test_initialize_rejects_incompatible_join_key_types():
    er = ErManager(
        entities=[ReviewMismatchedJoinProduct],
        session_factory=lambda: None,
    )
    transport = _IntrospectionTransport(
        _entity("StringKeyRemoteRow", product_id_type="str")
    )

    with pytest.raises(FederationError, match=r"id.*product_id.*incompatible"):
        await er.initialize(transport=transport)


@pytest.mark.asyncio
async def test_initialize_rejects_duplicate_remote_relationship_names():
    with pytest.raises((FederationError, ValueError), match=r"duplicate"):
        ErManager(
            entities=[ReviewDuplicateRelationshipProduct],
            session_factory=lambda: None,
        )


def test_materialization_preserves_required_scalar_fields():
    member_er = ErManager(
        entities=[ReviewRequiredSchemaRow],
        session_factory=lambda: None,
        service_name="review_remote",
    )
    payload = serialize_er_introspection(member_er)
    fragment = next(
        entity
        for entity in payload.entities
        if entity.typename == "ReviewRequiredSchemaRow"
    )

    registry = FederatedTypeRegistry()
    registry.materialize({"review_remote.ReviewRequiredSchemaRow": fragment})
    materialized = registry.get("review_remote.ReviewRequiredSchemaRow")

    assert materialized.model_fields["title"].annotation is str
    sdl = SDLGenerator([materialized]).generate(include_mutations=False)
    assert "title: String!" in sdl


def test_nested_selection_preserves_object_field_arguments():
    comments = FieldSelection(
        name="comments",
        arguments={"limit": 5},
        sub_fields={
            "items": FieldSelection(
                name="items",
                sub_fields={"text": FieldSelection(name="text")},
            )
        },
    )
    selection = FieldSelection(name="reviews", sub_fields={"comments": comments})

    query = build_gql_query(
        typename="ReviewRemoteRow",
        entry="by_product_id_in",
        arg_name="product_id_list",
        keys=[1],
        selection=selection,
        target_cls=object,
        join_remote="product_id",
    )

    assert "comments(limit: 5) {" in query


@pytest.mark.parametrize(
    ("annotation", "type_name", "value", "literal"),
    [
        (str, "str", "sku\n1", '"sku\\n1"'),
        (int, "int", 7, "product_id_list: [7]"),
        (float, "float", 1.5, "product_id_list: [1.5]"),
        (bool, "bool", True, "product_id_list: [true]"),
        (
            UUID,
            "UUID",
            UUID("12345678-1234-5678-1234-567812345678"),
            '"12345678-1234-5678-1234-567812345678"',
        ),
    ],
)
def test_supported_join_key_types_pass_validation_and_render(
    annotation,
    type_name,
    value,
    literal,
):
    source = create_model(
        f"Review{type_name}JoinSource",
        product_id=(annotation, ...),
    )
    relationship = RemoteRelationship(
        fk="product_id",
        target=review_remote.ReviewRemoteRow,
        name="review",
        join_remote="product_id",
    )

    _check_join_contract(
        source_entity=source,
        rrel=relationship,
        remote_field_type=type_name,
        batch_arg_type=f"list[{type_name}]",
    )
    query = build_gql_query(
        typename="ReviewRemoteRow",
        entry="by_product_id_in",
        arg_name="product_id_list",
        keys=[value],
        selection=FieldSelection(name="review"),
        target_cls=object,
        join_remote="product_id",
    )

    assert literal in query


def test_join_contract_rejects_incompatible_batch_argument_type():
    source = create_model("ReviewBatchJoinSource", product_id=(int, ...))
    relationship = RemoteRelationship(
        fk="product_id",
        target=review_remote.ReviewRemoteRow,
        name="review",
        join_remote="product_id",
    )

    with pytest.raises(FederationError, match=r"list\[str\].*incompatible"):
        _check_join_contract(
            source_entity=source,
            rrel=relationship,
            remote_field_type="int",
            batch_arg_type="list[str]",
        )


def test_join_contract_rejects_decimal_join_key():
    """Decimal is not a supported federation join-key type: member page_by
    buckets by the SQL column value, which mismatches the wire string key.
    Rejected at federate() validation (fail-fast), never at query time."""
    source = create_model("ReviewDecimalJoinSource", product_id=(Decimal, ...))
    relationship = RemoteRelationship(
        fk="product_id",
        target=review_remote.ReviewRemoteRow,
        name="review",
        join_remote="product_id",
    )

    with pytest.raises(FederationError, match=r"Unsupported.*Decimal"):
        _check_join_contract(
            source_entity=source,
            rrel=relationship,
            remote_field_type="Decimal",
            batch_arg_type="list[Decimal]",
        )


@pytest.mark.asyncio
async def test_http_rejection_surfaces_remote_error_detail():
    def reject(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"detail": "federation token rejected"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(reject),
        base_url="http://review-remote",
    )
    transport = GraphQLTransport(client=client)
    try:
        with pytest.raises(
            FederationTransportError,
            match="federation token rejected",
        ) as exc_info:
            await transport.get_json(
                "http://review-remote/nexusx/er-introspection"
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.retryable is False
    finally:
        await client.aclose()


class _MalformedGraphQLTransport:
    async def post_json(self, url: str, body: dict) -> dict:
        return {"data": {"ReviewRemoteRow": {}}}


@pytest.mark.asyncio
async def test_remote_loader_rejects_missing_batch_entry_in_response():
    target_cls = create_model(
        "ReviewRemoteRow",
        id=(int | None, None),
        product_id=(int | None, None),
        title=(str | None, None),
    )
    loader_cls = create_remote_loader(
        typename="ReviewRemoteRow",
        join_remote="product_id",
        endpoint="http://review-remote",
        target_cls=target_cls,
        transport=_MalformedGraphQLTransport(),
        is_list=True,
    )
    loader = loader_cls()
    set_remote_selection(
        loader,
        FieldSelection(
            name="reviews",
            sub_fields={"title": FieldSelection(name="title")},
        ),
    )

    with pytest.raises(RemoteQueryError):
        await loader.load_many([1])


class _RetryTransport(_IntrospectionTransport):
    def __init__(self) -> None:
        super().__init__(_entity("RetryRemoteRow"))
        self.get_calls = 0
        self.close_calls = 0

    async def get_json(self, url: str) -> dict:
        self.get_calls += 1
        if self.get_calls == 1:
            raise FederationTransportError("GET", url, "connection refused")
        return await super().get_json(url)

    async def close(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_initialize_reuses_default_transport_across_retries(monkeypatch):
    transport = _RetryTransport()
    created = 0

    def transport_factory():
        nonlocal created
        created += 1
        return transport

    monkeypatch.setattr(
        "nexusx.federation.manager.GraphQLTransport",
        transport_factory,
    )
    er = ErManager(
        entities=[ReviewRetryProduct],
        session_factory=lambda: None,
    )

    with pytest.raises(FederationTransportError, match="connection refused"):
        await er.initialize()
    await er.initialize()

    assert created == 1
    assert transport.get_calls == 2
    assert er._federation_transport is transport


@pytest.mark.asyncio
async def test_handler_aclose_closes_transport_once():
    handler = GraphQLHandler(
        base=ReviewLifecycleBase,
        session_factory=lambda: None,
    )
    transport = _RetryTransport()
    handler.er._federation_transport = transport

    await handler.aclose()
    await handler.aclose()

    assert transport.close_calls == 1
    assert handler.er._federation_transport is None
