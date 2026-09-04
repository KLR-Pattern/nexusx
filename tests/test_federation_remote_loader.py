"""US1 — RemoteLoader: gql nested-query construction + response alignment."""

from __future__ import annotations

import uuid

import pytest
from pydantic import create_model
from sqlmodel import Field, SQLModel

from nexusx.federation.remote_loader import (
    create_remote_loader,
    set_remote_selection,
)
from nexusx.query_parser import FieldSelection


class FakeTransport:
    """Records posted gql bodies; returns a canned {data} response."""

    def __init__(self, data):
        self.data = data
        self.posts: list[tuple[str, dict]] = []

    async def post_json(self, url, body):
        self.posts.append((url, body))
        return {"data": self.data}


def _selection(*scalars):
    return FieldSelection(
        name="reviews",
        sub_fields={s: FieldSelection(name=s) for s in scalars},
    )


@pytest.mark.asyncio
async def test_remote_loader_builds_gql_and_aligns_to_many():
    target_cls = create_model(
        "Review",
        id=(int | None, None),
        product_id=(int | None, None),
        title=(str | None, None),
        rating=(int | None, None),
    )
    data = {
        "Review": {
            "by_product_id_in": [
                {"id": 1, "product_id": 1, "title": "R1", "rating": 5},
                {"id": 2, "product_id": 1, "title": "R2", "rating": 3},
                {"id": 3, "product_id": 2, "title": "R3", "rating": 4},
            ]
        }
    }
    transport = FakeTransport(data)
    loader_cls = create_remote_loader(
        typename="Review",
        join_remote="product_id",
        endpoint="http://reviews",
        target_cls=target_cls,
        transport=transport,
        is_list=True,
        arg_name="product_id_list",
    )
    loader = loader_cls()
    set_remote_selection(loader, _selection("title", "rating"))

    results = await loader.load_many([1, 2])

    # Alignment: key 1 -> [R1, R2], key 2 -> [R3].
    assert [r.title for r in results[0]] == ["R1", "R2"]
    assert [r.title for r in results[1]] == ["R3"]

    # Exactly one gql POST, to /graphql, with the right entry + keys.
    assert len(transport.posts) == 1
    url, body = transport.posts[0]
    assert url == "http://reviews/graphql"
    q = body["query"]
    assert "Review" in q
    assert "by_product_id_in(product_id_list: [1, 2])" in q
    # join key is always requested (for alignment) even if client didn't select it.
    assert "product_id" in q


@pytest.mark.asyncio
async def test_remote_loader_to_one_missing_key_maps_none():
    target_cls = create_model("User", id=(int | None, None), name=(str | None, None))
    data = {"User": {"by_id_in": [{"id": 7, "name": "Bob"}]}}
    transport = FakeTransport(data)
    loader_cls = create_remote_loader(
        typename="User",
        join_remote="id",
        endpoint="http://users",
        target_cls=target_cls,
        transport=transport,
        is_list=False,
        arg_name="id_list",
    )
    loader = loader_cls()
    set_remote_selection(
        loader, FieldSelection(name="author", sub_fields={"name": FieldSelection(name="name")})
    )

    results = await loader.load_many([7, 999])
    assert results[0].name == "Bob"
    assert results[1] is None  # missing key -> None (to-one)


@pytest.mark.asyncio
async def test_remote_loader_batches_multiple_loads_into_one_query():
    """DataLoader coalesces concurrent loads into a single batch_load_fn call."""
    target_cls = create_model(
        "Review",
        id=(int | None, None), product_id=(int | None, None), title=(str | None, None),
    )
    data = {"Review": {"by_product_id_in": [
        {"id": 1, "product_id": p, "title": f"R{p}"} for p in (1, 2, 3, 4, 5)
    ]}}
    transport = FakeTransport(data)
    loader_cls = create_remote_loader(
        typename="Review", join_remote="product_id", endpoint="http://reviews",
        target_cls=target_cls, transport=transport, is_list=False,
        arg_name="product_id_list",
    )
    loader = loader_cls()
    set_remote_selection(
        loader, FieldSelection(name="reviews", sub_fields={"title": FieldSelection(name="title")})
    )

    # Five separate .load() calls in the same frame → one batched gql query.
    import asyncio
    vals = await asyncio.gather(*(loader.load(p) for p in (1, 2, 3, 4, 5)))
    assert [v.title for v in vals] == ["R1", "R2", "R3", "R4", "R5"]
    assert len(transport.posts) == 1  # SC-003: one query for N keys


@pytest.mark.asyncio
async def test_remote_loader_aligns_uuid_join_key():
    """P0: UUID join keys align even though the remote echoes them as strings.

    Before normalization, ``buckets`` was keyed by the remote's string form
    while the lookup used the local UUID instance → silent miss → None.
    """
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    target_cls = create_model(
        "Thing", id=(int | None, None), owner_id=(str | None, None), name=(str | None, None)
    )
    data = {"Thing": {"by_owner_id_in": [
        {"id": 1, "owner_id": str(u1), "name": "A"},
        {"id": 2, "owner_id": str(u2), "name": "B"},
    ]}}
    transport = FakeTransport(data)
    loader_cls = create_remote_loader(
        typename="Thing", join_remote="owner_id", endpoint="http://things",
        target_cls=target_cls, transport=transport, is_list=False,
        arg_name="owner_id_list",
    )
    loader = loader_cls()
    set_remote_selection(
        loader, FieldSelection(name="t", sub_fields={"name": FieldSelection(name="name")})
    )

    results = await loader.load_many([u1, u2])
    assert results[0].name == "A"
    assert results[1].name == "B"

    # Outbound: UUIDs rendered as quoted strings in the gql literal.
    q = transport.posts[0][1]["query"]
    assert f'"{u1}"' in q and f'"{u2}"' in q


@pytest.mark.asyncio
async def test_remote_loader_uses_explicit_arg_name():
    """P1a: arg_name from the contract is used instead of the <key>_list convention."""
    target_cls = create_model(
        "Review", id=(int | None, None), product_id=(int | None, None), title=(str | None, None)
    )
    transport = FakeTransport(
        {"Review": {"by_product_id_in": [{"product_id": 1, "title": "R1"}]}}
    )
    loader_cls = create_remote_loader(
        typename="Review", join_remote="product_id", endpoint="http://reviews",
        target_cls=target_cls, transport=transport, is_list=False,
        arg_name="product_ids",  # member renamed the argument
    )
    loader = loader_cls()
    set_remote_selection(loader, _selection("title"))
    await loader.load_many([1])
    q = transport.posts[0][1]["query"]
    assert "by_product_id_in(product_ids: [1])" in q


def test_batch_roots_introspect_arg_contract():
    """P1a: _batch_roots reads the real arg name/type from the generated root."""
    from nexusx.federation.introspect import _batch_roots
    from nexusx.standard_queries import AutoQueryConfig, add_standard_queries

    class T(SQLModel, table=True):
        __tablename__ = "fed_p1a_argroots"
        __federation_keys__ = ["product_id"]
        id: int | None = Field(default=None, primary_key=True)
        product_id: int

    add_standard_queries([T], AutoQueryConfig(), lambda: None)
    roots = {r.name: r for r in _batch_roots(T)}
    br = roots["by_product_id_in"]
    assert br.arg_name == "product_id_list"
    assert br.arg_type == "list[int]"


# ──────────────────────────────────────────────────────────────────────
# specs/023 US4: the wire never carries aliases (mounter-side boundary gate)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wire_never_carries_aliases_flat():
    """Aliased selection keys must not leak into the member-bound query.

    Simulates the post-023 parser tree: sub_fields keyed by RESPONSE key
    (alias when present) with FieldSelection.name carrying the real field
    name. The renderer must emit original field names only.
    """
    target_cls = create_model(
        "WireReview",
        id=(int | None, None),
        product_id=(int | None, None),
        title=(str | None, None),
    )
    transport = FakeTransport(
        {"WireReview": {"by_product_id_in": [{"product_id": 1, "title": "R1"}]}}
    )
    loader_cls = create_remote_loader(
        typename="WireReview", join_remote="product_id", endpoint="http://reviews",
        target_cls=target_cls, transport=transport, is_list=False,
        arg_name="product_id_list",
    )
    # Response-keyed tree exactly as the new parser would build it.
    aliased = FieldSelection(
        name="WireReview",
        sub_fields={
            "t1": FieldSelection(name="title", alias="t1"),
            "pid": FieldSelection(name="product_id", alias="pid"),
        },
    )
    loader = loader_cls()
    set_remote_selection(loader, aliased)
    await loader.load_many([1])
    q = transport.posts[0][1]["query"]
    assert "title" in q and "product_id" in q
    assert "t1:" not in q and "pid:" not in q


@pytest.mark.asyncio
async def test_wire_never_carries_aliases_nested():
    """Nested aliased sub-selections also render with original field names."""
    target_cls = create_model(
        "WireUser",
        id=(int | None, None),
        name=(str | None, None),
    )
    transport = FakeTransport(
        {"WireUser": {"by_id_in": [{"id": 1, "name": "A"}]}}
    )
    loader_cls = create_remote_loader(
        typename="WireUser", join_remote="id", endpoint="http://users",
        target_cls=target_cls, transport=transport, is_list=False,
        arg_name="id_list",
    )
    aliased = FieldSelection(
        name="WireUser",
        sub_fields={
            "name": FieldSelection(name="name"),
            "friend": FieldSelection(
                name="friend",
                sub_fields={"n": FieldSelection(name="name", alias="n")},
            ),
        },
    )
    loader = loader_cls()
    set_remote_selection(loader, aliased)
    await loader.load_many([1])
    q = transport.posts[0][1]["query"]
    assert "friend" in q and "name" in q
    assert "n:" not in q


# ──────────────────────────────────────────────────────────────────────
# Mindmap #14 修复④ / 实锤缺陷 1: distinct page params MUST get distinct
# loader instances (REMOTE_PAGED selections wrap {items, pagination}, so
# type_key is always None there and force_split alone never fired —
# concurrent limit=5 / limit=10 shared one instance and overwrote each
# other's _remote_page_params).
# ──────────────────────────────────────────────────────────────────────


class TestPagedParamsSplit:
    def test_fetch_passes_params_key_for_isolation(self):
        """fetch_remote_subtree must route page params into get_loader's
        params_key — the per-params split that isolates concurrent
        limit=5 / limit=10 loads (defect 1)."""
        import asyncio

        from nexusx.federation.remote_loader import fetch_remote_subtree
        from nexusx.loader.pagination import Paged
        from nexusx.loader.registry import ErManager
        from nexusx.query_parser import FieldSelection
        from pydantic import BaseModel

        class Target(BaseModel):
            id: int
            product_id: int

        registry = ErManager(session_factory=None, entities=[])
        rel_info = type("R", (), {})()
        rel_info.target_entity = Target
        rel_info.fk_field = "product_id"
        rel_info.page_loader = type("L2", (), {})

        sel = FieldSelection(
            name="Target",
            sub_fields={
                "items": FieldSelection(name="items", sub_fields={
                    "id": FieldSelection(name="id")}),
                "pagination": FieldSelection(name="pagination"),
            },
        )

        calls: list[dict] = []

        def fake_get_loader(loader_cls, **kwargs):
            calls.append(kwargs)

            class NoopLoader:
                async def load_many(self, keys):
                    return []

            return NoopLoader()

        registry.get_loader = fake_get_loader

        async def run(params):
            return await fetch_remote_subtree(
                registry=registry, rel_info=rel_info, parents=[],
                selection=sel, paged=True, page_params=params,
            )

        async def main():
            await asyncio.gather(
                run(Paged(limit=5)), run(Paged(limit=10)), run(Paged(limit=5)),
            )

        asyncio.run(main())
        keys = [c["params_key"] for c in calls]
        assert (5, 0, None, None) in keys
        assert (10, 0, None, None) in keys

    def test_registry_params_key_isolates_instances(self):
        """The registry-level guarantee: distinct params_key → distinct
        instances (side-channel overwrite impossible); identical → shared
        (batching preserved)."""
        from nexusx.loader.registry import ErManager

        registry = ErManager(session_factory=None, entities=[])

        class L:
            pass

        a = registry.get_loader(L, type_key=None, force_split=True,
                                params_key=(5, 0, None, None))
        b = registry.get_loader(L, type_key=None, force_split=True,
                                params_key=(10, 0, None, None))
        c = registry.get_loader(L, type_key=None, force_split=True,
                                params_key=(5, 0, None, None))
        assert a is not b
        assert a is c

    def test_paged_selection_alone_yields_none_type_key(self):
        """The root cause, locked: the {items, pagination} wrapper is not a
        target-entity field set, so the selection fingerprint is None."""
        from nexusx.loader.query_meta import generate_type_key_from_selection
        from nexusx.query_parser import FieldSelection
        from pydantic import BaseModel

        class Target(BaseModel):
            id: int

        sel = FieldSelection(
            name="Target",
            sub_fields={
                "items": FieldSelection(name="items", sub_fields={
                    "id": FieldSelection(name="id")}),
                "pagination": FieldSelection(name="pagination"),
            },
        )
        assert generate_type_key_from_selection(sel, Target, fk_lookup={}) is None


# ──────────────────────────────────────────────────────────────────────
# Mindmap #14 修复⑤ / 实锤缺陷 5: federation limits are clamped at the
# dispatch layer (the bound used to live only on the local PageArgs path).
# ──────────────────────────────────────────────────────────────────────


class TestFederationLimitClamp:
    def test_clamp_caps_limit(self):
        from nexusx.loader.pagination import Paged

        assert Paged(limit=100000).clamp(100).limit == 100
        assert Paged(limit=50).clamp(100).limit == 50
        # None (full-fetch) and no-bound pass through untouched
        assert Paged(limit=None).clamp(100).limit is None
        assert Paged(limit=100000).clamp(None).limit == 100000
        # other params survive the clamp
        p = Paged(limit=100000, offset=7, order="RATING").clamp(100)
        assert (p.limit, p.offset, p.order) == (100, 7, "RATING")

    @pytest.mark.asyncio
    async def test_fetch_clamps_to_rel_max_page_size(self):
        """A β fetch with limit=100000 against a relationship whose
        max_page_size is the default 100 must send limit: 100 on the wire."""
        from nexusx.federation.remote_loader import (
            create_paginated_remote_loader,
            paged_from_selection,
            set_remote_page_params,
            set_remote_selection,
        )
        from nexusx.query_parser import FieldSelection
        from pydantic import BaseModel

        class Target(BaseModel):
            id: int
            product_id: int

        transport = FakeTransport({
            "Target": {"page_by_product_id_in": []}
        })
        loader_cls = create_paginated_remote_loader(
            typename="Target", join_remote="product_id",
            endpoint="http://t", target_cls=Target,
            transport=transport, arg_name="product_id_list",
            default_order="BY_ID",
        )
        sel = FieldSelection(
            name="Target",
            arguments={"limit": 100000},
            sub_fields={
                "items": FieldSelection(name="items", sub_fields={
                    "id": FieldSelection(name="id")}),
                "pagination": FieldSelection(name="pagination"),
            },
        )
        loader = loader_cls()
        set_remote_selection(loader, sel)
        # the dispatch layer resolved+clamped params (fetch does this; the
        # test replays it — limit 100000 must arrive on the loader already
        # clamped to the rel's default max of 100)
        params = paged_from_selection(sel).clamp(100)
        set_remote_page_params(loader, params)

        await loader.load_many([1])
        q = transport.posts[0][1]["query"]
        assert "limit: 100" in q
        assert "100000" not in q
