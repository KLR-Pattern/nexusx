"""Regression coverage for the DTO federation branch review findings."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, create_model
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import DefineSubset, ErManager, Loader, SubsetConfig
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.contract import (
    BatchRoot,
    DTOFragment,
    DTOIntrospectionResponse,
    EntityFragment,
    ERIntrospectionResponse,
    FieldDescriptor,
    RelDescriptor,
)
from nexusx.federation.manager import FederationError
from nexusx.federation.registry import FederatedTypeRegistry
from nexusx.federation.remote_loader import RemoteQueryError, create_dto_remote_loader
from nexusx.standard_queries import add_dto_batch_roots

reviews_service = RemoteService("reviews", url="http://reviews")
alpha_service = RemoteService("alpha", url="http://alpha")
beta_service = RemoteService("beta", url="http://beta")
deferred_source_service = RemoteService(
    "deferred-source", url="http://deferred-source",
)
deferred_leaf_service = RemoteService("deferred-leaf")


class _PureProduct(SQLModel, table=True):
    __tablename__ = "dto_review_pure_product"

    id: int | None = Field(default=None, primary_key=True)


class _PureProductDTO(DefineSubset):
    __subset__ = (_PureProduct, ("id",))
    reviews: list[reviews_service.ReviewDTO] = Field(default_factory=list)

    def resolve_reviews(self, loader=Loader("reviews")):
        return loader.load(self.id)


class _AlphaOwner(SQLModel, table=True):
    __tablename__ = "dto_review_alpha_owner"

    id: int | None = Field(default=None, primary_key=True)


class _BetaOwner(SQLModel, table=True):
    __tablename__ = "dto_review_beta_owner"

    id: int | None = Field(default=None, primary_key=True)


class _AlphaOwnerDTO(DefineSubset):
    __subset__ = (_AlphaOwner, ("id",))
    items: list[alpha_service.AlphaItemDTO] = Field(default_factory=list)

    def resolve_items(self, loader=Loader("items")):
        return loader.load(self.id)


class _BetaOwnerDTO(DefineSubset):
    __subset__ = (_BetaOwner, ("id",))
    items: list[beta_service.BetaItemDTO] = Field(default_factory=list)

    def resolve_items(self, loader=Loader("items")):
        return loader.load(self.id)


class _JoinProduct(SQLModel, table=True):
    __tablename__ = "dto_review_join_product"

    id: int | None = Field(default=None, primary_key=True)


class _JoinReview(SQLModel, table=True):
    __tablename__ = "dto_review_join_review"

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="dto_review_join_product.id")
    title: str


class _HiddenJoinDTO(DefineSubset):
    __subset__ = SubsetConfig(
        kls=_JoinReview,
        fields=("title",),
        federation_public=True,
        federation_join_key="product_id",
    )


class _DeferredOwner(SQLModel, table=True):
    __tablename__ = "dto_review_deferred_owner"

    id: int | None = Field(default=None, primary_key=True)
    __relationships__ = [
        RemoteRelationship(
            fk="id",
            target=list[deferred_source_service.Review],
            name="source_reviews",
            join_remote="product_id",
        ),
    ]


class DeferredReviewDTO(DefineSubset):
    __subset__ = (
        deferred_source_service.Review,
        ("id", "product_id", "title"),
    )
    comments: list[deferred_leaf_service.CommentDTO] = Field(default_factory=list)

    def resolve_comments(self, loader=Loader("comments")):
        return loader.load(self.id)


def _dto_fragment(
    name: str,
    *,
    fields: list[tuple[str, str]],
    join_key: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "base_entity": name.removesuffix("DTO"),
        "scalar_fields": [
            {"name": field_name, "type_name": type_name}
            for field_name, type_name in fields
        ],
        "join_key": join_key,
        "batch_root": {
            "name": f"by_{join_key}_in",
            "arg_name": f"{join_key}_list",
            "arg_type": "",
        },
        "remote_refs": [],
    }


class _DTOTransport:
    def __init__(self) -> None:
        self.posts: list[str] = []

    async def get_json(self, url: str) -> dict[str, Any]:
        if url == "http://reviews/nexusx/dto-introspection":
            return {
                "service_name": "reviews",
                "dtos": [
                    _dto_fragment(
                        "ReviewDTO",
                        fields=[("title", "str"), ("product_id", "int")],
                        join_key="product_id",
                    )
                ],
            }
        if url == "http://alpha/nexusx/dto-introspection":
            return {
                "service_name": "alpha",
                "dtos": [
                    _dto_fragment(
                        "AlphaItemDTO",
                        fields=[("id", "int"), ("source", "str")],
                        join_key="id",
                    )
                ],
            }
        if url == "http://beta/nexusx/dto-introspection":
            return {
                "service_name": "beta",
                "dtos": [
                    _dto_fragment(
                        "BetaItemDTO",
                        fields=[("id", "int"), ("source", "str")],
                        join_key="id",
                    )
                ],
            }
        raise AssertionError(f"unexpected introspection request: {url}")

    async def post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        self.posts.append(url)
        key = body["keys"][0]
        if url == "http://reviews/nexusx/dto-batch":
            return {"data": [{"title": "ok", "product_id": key}]}
        if url == "http://alpha/nexusx/dto-batch":
            return {"data": [{"id": key, "source": "alpha"}]}
        if url == "http://beta/nexusx/dto-batch":
            return {"data": [{"id": key, "source": "beta"}]}
        raise AssertionError(f"unexpected batch request: {url}")

    async def close(self) -> None:
        return None


class _DeferredDTOTransport:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    async def get_json(self, url: str) -> dict[str, Any]:
        if url == "http://deferred-source/nexusx/er-introspection":
            return ERIntrospectionResponse(
                service_name="deferred-source",
                entities=[
                    EntityFragment(
                        typename="Review",
                        pk_field="id",
                        scalar_fields=[
                            FieldDescriptor(name="id", type_name="int"),
                            FieldDescriptor(name="product_id", type_name="int"),
                            FieldDescriptor(name="title", type_name="str"),
                        ],
                        relationships=[
                            RelDescriptor(
                                name="leaf_rows",
                                direction="ONETOMANY",
                                fk_field="id",
                                target_typename="LeafEntity",
                                is_list=True,
                                target_service="deferred-leaf",
                                target_endpoint="http://deferred-leaf",
                            )
                        ],
                        batch_roots=[
                            BatchRoot(
                                name="by_product_id_in",
                                arg_name="product_id_list",
                                arg_type="list[int]",
                            )
                        ],
                    )
                ],
            ).model_dump()
        if url == "http://deferred-leaf/nexusx/er-introspection":
            return ERIntrospectionResponse(
                service_name="deferred-leaf",
                entities=[
                    EntityFragment(
                        typename="LeafEntity",
                        pk_field="id",
                        scalar_fields=[
                            FieldDescriptor(name="id", type_name="int"),
                        ],
                        batch_roots=[
                            BatchRoot(
                                name="by_id_in",
                                arg_name="id_list",
                                arg_type="list[int]",
                            )
                        ],
                    )
                ],
            ).model_dump()
        if url == "http://deferred-source/nexusx/dto-introspection":
            return DTOIntrospectionResponse(
                service_name="deferred-source",
            ).model_dump()
        if url == "http://deferred-leaf/nexusx/dto-introspection":
            return DTOIntrospectionResponse(
                service_name="deferred-leaf",
                dtos=[
                    DTOFragment(
                        name="CommentDTO",
                        base_entity="Comment",
                        scalar_fields=[
                            FieldDescriptor(name="id", type_name="int"),
                            FieldDescriptor(name="review_id", type_name="int"),
                            FieldDescriptor(name="text", type_name="str"),
                        ],
                        join_key="review_id",
                        batch_root=BatchRoot(
                            name="by_review_id_in",
                            arg_name="review_id_list",
                            arg_type="list[int]",
                        ),
                    )
                ],
            ).model_dump()
        raise AssertionError(f"unexpected GET {url}")

    async def post_json(
        self,
        url: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        self.posts.append((url, body))
        assert url == "http://deferred-leaf/nexusx/dto-batch"
        review_id = body["keys"][0]
        return {
            "data": [
                {
                    "id": 101,
                    "review_id": review_id,
                    "text": "nested",
                }
            ]
        }


def test_future_annotations_remote_ref_is_deferred() -> None:
    future_service = RemoteService("future-reviews", url="http://future-reviews")

    class FutureSource(BaseModel):
        id: int

    class FutureDTO(DefineSubset):
        __subset__ = (FutureSource, ("id",))
        reviews: list[future_service.ReviewDTO] = Field(default_factory=list)

    refs = getattr(FutureDTO, "__nexusx_remote_field_refs__", None)
    assert refs is not None
    assert "reviews" in refs
    assert FutureDTO.model_fields["reviews"].annotation is Any


@pytest.mark.asyncio
async def test_deferred_source_dto_wires_nested_remote_field() -> None:
    transport = _DeferredDTOTransport()
    placeholder = DeferredReviewDTO
    er = ErManager(
        entities=[_DeferredOwner],
        session_factory=lambda: None,
        service_name="catalog",
        dto_classes=[placeholder],
    )

    await er.initialize(transport=transport)

    [resolved_cls] = er.get_dto_classes()
    assert resolved_cls is DeferredReviewDTO
    assert resolved_cls is not placeholder
    refs = getattr(resolved_cls, "__nexusx_remote_field_refs__", None)
    assert refs is not None and "comments" in refs
    assert er.get_dto_loader(resolved_cls, "comments") is not None

    Resolver = er.create_resolver()
    [resolved] = await Resolver().resolve([
        resolved_cls(id=1, product_id=7, title="remote"),
    ])
    assert [comment.text for comment in resolved.comments] == ["nested"]
    assert transport.posts == [
        (
            "http://deferred-leaf/nexusx/dto-batch",
            {
                "dto": "CommentDTO",
                "join_key": "review_id",
                "keys": [1],
            },
        )
    ]


@pytest.mark.asyncio
async def test_pure_gamma_initializes_without_beta_relationship() -> None:
    transport = _DTOTransport()
    er = ErManager(
        entities=[_PureProduct],
        session_factory=lambda: None,
        service_name="catalog",
        dto_classes=[_PureProductDTO],
    )

    assert er._pending_remote_rels == []
    await er.initialize(transport=transport)

    assert er.get_dto_loader(_PureProductDTO, "reviews") is not None
    Resolver = er.create_resolver()
    [resolved] = await Resolver().resolve([_PureProductDTO(id=7)])
    assert [review.title for review in resolved.reviews] == ["ok"]
    assert transport.posts == ["http://reviews/nexusx/dto-batch"]


@pytest.mark.asyncio
async def test_pure_gamma_requires_a_discoverable_endpoint() -> None:
    orphan_service = RemoteService("orphan")

    class OrphanDTO(DefineSubset):
        __subset__ = (_PureProduct, ("id",))
        reviews: list[orphan_service.ReviewDTO] = Field(default_factory=list)

    er = ErManager(
        entities=[_PureProduct],
        session_factory=lambda: None,
        service_name="catalog",
        dto_classes=[OrphanDTO],
    )

    with pytest.raises(FederationError, match="has no endpoint"):
        await er.initialize(transport=_DTOTransport())


@pytest.mark.asyncio
async def test_dto_loaders_are_scoped_by_owner_dto() -> None:
    transport = _DTOTransport()
    er = ErManager(
        entities=[_AlphaOwner, _BetaOwner],
        session_factory=lambda: None,
        service_name="mounter",
        dto_classes=[_AlphaOwnerDTO, _BetaOwnerDTO],
    )
    await er.initialize(transport=transport)

    Resolver = er.create_resolver()
    [alpha] = await Resolver().resolve([_AlphaOwnerDTO(id=1)])
    [beta] = await Resolver().resolve([_BetaOwnerDTO(id=2)])

    assert alpha.items[0].source == "alpha"
    assert beta.items[0].source == "beta"
    assert transport.posts == [
        "http://alpha/nexusx/dto-batch",
        "http://beta/nexusx/dto-batch",
    ]


@pytest.mark.asyncio
async def test_auto_hidden_join_key_is_present_in_batch_payload() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        session.add(_JoinProduct(id=10))
        session.add(_JoinReview(id=1, product_id=10, title="hidden key"))
        await session.commit()

    er = ErManager(
        entities=[_JoinProduct, _JoinReview],
        session_factory=session_factory,
        service_name="reviews",
        dto_classes=[_HiddenJoinDTO],
    )
    add_dto_batch_roots(er)
    batch_fn, _join_key = er._dto_batch_roots[_HiddenJoinDTO.__name__]

    rows = await batch_fn([10])
    assert rows == [{"title": "hidden key", "id": 1, "product_id": 10}]
    await engine.dispose()


def test_nested_dto_fields_rebuild_to_materialized_types() -> None:
    batch_root = BatchRoot(name="by_id_in", arg_name="id_list")
    fragments = {
        "nested.ChildDTO": DTOFragment(
            name="ChildDTO",
            base_entity="Child",
            scalar_fields=[FieldDescriptor(name="name", type_name="str")],
            join_key="id",
            batch_root=batch_root,
        ),
        "nested.ParentDTO": DTOFragment(
            name="ParentDTO",
            base_entity="Parent",
            scalar_fields=[
                FieldDescriptor(name="id", type_name="int"),
                FieldDescriptor(name="children", type_name="list[ChildDTO]"),
            ],
            join_key="id",
            batch_root=batch_root,
        ),
    }
    registry = FederatedTypeRegistry()
    registry.materialize_dtos(fragments)

    ParentDTO = registry.get("nested.ParentDTO")
    ChildDTO = registry.get("nested.ChildDTO")
    parent: BaseModel = ParentDTO.model_validate(
        {"id": 1, "children": [{"name": "typed"}]}
    )

    assert ParentDTO.model_fields["children"].annotation == list[ChildDTO]
    assert isinstance(parent.children[0], ChildDTO)


@pytest.mark.asyncio
async def test_dto_loader_rejects_rows_missing_join_key() -> None:
    class MissingKeyTransport:
        async def post_json(
            self,
            _url: str,
            _body: dict[str, Any],
        ) -> dict[str, Any]:
            return {"data": [{"title": "missing"}]}

    target = create_model(
        "ReviewDTO",
        title=(str, None),
        product_id=(int, None),
    )
    loader_cls = create_dto_remote_loader(
        typename="ReviewDTO",
        join_key="product_id",
        endpoint="http://reviews",
        target_cls=target,
        transport=MissingKeyTransport(),
        is_list=True,
    )

    with pytest.raises(RemoteQueryError, match="missing required join key"):
        await loader_cls().load_many([10])
