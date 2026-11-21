"""Relationship variants contract tests (2026-11 variants refactor, plan §九).

Locks two things:

1. **Literal expectation table** — the polymorphic ``can_paginate`` /
   ``is_paginated`` judgments for all four variants, exactly as the old
   kind × pagination × page_loader truth table dictated (demo scenario 2
   frozen as a test).
2. **Illegal states are unrepresentable** — the contradictions the flat
   ``RelationshipInfo`` silently accepted (demo scenario 3) now fail at
   construction with ``TypeError``: no validation code, the types say it.
"""

from __future__ import annotations

import dataclasses

import pytest

from nexusx.loader.registry import (
    LocalRelationship,
    RemoteCoalescedRelationship,
    RemotePagedRelationship,
    RemotePlainRelationship,
    RelationshipInfo,
)


def _local(**over) -> LocalRelationship:
    base = dict(
        name="reviews", direction="ONETOMANY", fk_field="product_id",
        target_entity=object, is_list=True,
        loader=object,
    )
    base.update(over)
    return LocalRelationship(**base)


# ---------------------------------------------------------------------------
# 1. Literal expectation table (demo 场景 2 固化)
# ---------------------------------------------------------------------------


class TestExpectationTable:
    """variant × (can_paginate, is_paginated) — the whole truth table."""

    def test_local_assembled(self):
        rel = _local(page_loader=object())
        assert rel.can_paginate is True  # SQL slices anytime — capability constant
        assert rel.is_paginated is True  # assembled (order_by declared)

    def test_local_not_assembled(self):
        """Capability without assembly: can_paginate stays True, shape stays flat."""
        rel = _local(page_loader=None)
        assert rel.can_paginate is True
        assert rel.is_paginated is False

    def test_local_scalar_never_paginates(self):
        rel = _local(is_list=False, direction="MANYTOONE", page_loader=None)
        assert rel.can_paginate is True  # capability is about the SOURCE
        assert rel.is_paginated is False  # but a scalar field has no window

    def test_remote_plain(self):
        rel = RemotePlainRelationship(
            name="author", direction="MANYTOONE", fk_field="author_id",
            target_entity=object, is_list=True,
            loader=object, target_service="UserSvc",
        )
        assert rel.can_paginate is False  # no wire channel
        assert rel.is_paginated is False

    def test_remote_paged(self):
        rel = RemotePagedRelationship(
            name="reviews", direction="ONETOMANY", fk_field="product_id",
            target_entity=object, is_list=True,
            loader=object, page_loader=object(), page_capability=object(),
            target_service="ReviewSvc",
        )
        assert rel.can_paginate is True  # capability is the wire shape
        assert rel.is_paginated is True

    def test_coalesced_paginated(self):
        rel = RemoteCoalescedRelationship(
            name="stats", direction="ONETOMANY", fk_field="product_id",
            target_entity=object, is_list=True,
            target_service="StatSvc", paginated=True,
        )
        assert rel.can_paginate is True
        assert rel.is_paginated is True

    def test_coalesced_unpaginated(self):
        rel = RemoteCoalescedRelationship(
            name="stats", direction="ONETOMANY", fk_field="product_id",
            target_entity=object, is_list=True,
            target_service="StatSvc", paginated=False,
        )
        assert rel.can_paginate is False
        assert rel.is_paginated is False


# ---------------------------------------------------------------------------
# 2. Illegal states are unrepresentable (demo 场景 3 成为生产事实)
# ---------------------------------------------------------------------------


class TestIllegalStatesUnrepresentable:
    def test_coalesced_with_page_loader_is_typeerror(self):
        """kind=COALESCED + page_loader 静默构造的旧世界死因存档。"""
        with pytest.raises(TypeError):
            RemoteCoalescedRelationship(
                name="stats", direction="ONETOMANY", fk_field="product_id",
                target_entity=object, is_list=True,
                target_service="StatSvc", paginated=True,
                page_loader=object(),
            )

    def test_paged_remote_without_page_loader_is_typeerror(self):
        """声明了分页却没有加载器——构造即承诺，没有中间态。"""
        with pytest.raises(TypeError):
            RemotePagedRelationship(
                name="reviews", direction="ONETOMANY", fk_field="product_id",
                target_entity=object, is_list=True,
                loader=object, target_service="ReviewSvc",
                # page_loader / page_capability missing
            )

    def test_plain_remote_with_page_loader_is_typeerror(self):
        with pytest.raises(TypeError):
            RemotePlainRelationship(
                name="author", direction="MANYTOONE", fk_field="author_id",
                target_entity=object, is_list=True,
                loader=object, target_service="UserSvc",
                page_loader=object(),
            )

    def test_base_is_abstract_by_convention(self):
        """The base carries no judgment — consumers must hold a variant."""
        rel = RelationshipInfo(
            name="x", direction="ONETOMANY", fk_field="x_id",
            target_entity=object, is_list=True,
        )
        with pytest.raises(NotImplementedError):
            rel.can_paginate


# ---------------------------------------------------------------------------
# 3. Taxonomy invariants
# ---------------------------------------------------------------------------


class TestTaxonomy:
    def test_all_variants_are_dataclasses(self):
        for cls in (
            LocalRelationship, RemotePlainRelationship,
            RemotePagedRelationship, RemoteCoalescedRelationship,
        ):
            assert dataclasses.is_dataclass(cls)

    def test_variants_subclass_base(self):
        for cls in (
            LocalRelationship, RemotePlainRelationship,
            RemotePagedRelationship, RemoteCoalescedRelationship,
        ):
            assert issubclass(cls, RelationshipInfo)

    def test_local_has_no_target_service_field(self):
        """「本地关系带服务前缀」不可表示——那是远程变体的事。"""
        rel = _local()
        assert not hasattr(rel, "target_service")


class TestImmutability:
    """Frozen variants — the smuggling channel is sealed (review 2026-11).

    A mutable dataclass would let ``coalesced.page_loader = X`` succeed
    silently; guarded readers (``getattr(rel_info, "page_loader", None)``)
    would then see the smuggled state and bypass the type discrimination —
    illegal states would become representable again. Frozen kills that at
    the only place it could start.
    """

    def test_all_variants_are_frozen(self):
        rel = _local()
        with pytest.raises(dataclasses.FrozenInstanceError):
            rel.page_loader = object()  # type: ignore[misc]

    def test_smuggling_a_page_loader_onto_coalesced_is_frozenerror(self):
        """The exact channel P1 sealed: setattr on a loader-less variant."""
        rel = RemoteCoalescedRelationship(
            name="reviews", direction="ONETOMANY", fk_field="product_id",
            target_entity=object, is_list=True,
            target_service="ProductSvc", paginated=True,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rel.page_loader = object()  # type: ignore[misc]
