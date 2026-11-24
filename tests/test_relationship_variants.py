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
    RelationshipInfo,
    RemoteCoalescedRelationship,
    RemotePagedRelationship,
    RemotePlainRelationship,
    page_capability_of,
    plain_loader_of,
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

    def test_base_is_an_abc(self):
        """The base carries no judgment — it cannot even be instantiated
        (spec 026 / issue #160 DESIGN_5: abstract by type, not by convention)."""
        with pytest.raises(TypeError, match="abstract"):
            RelationshipInfo(
                name="x", direction="ONETOMANY", fk_field="x_id",
                target_entity=object, is_list=True,
            )

    def test_loading_variants_require_a_loader(self):
        """``loader`` is a required field on the three loading variants."""
        for cls in (LocalRelationship, RemotePlainRelationship, RemotePagedRelationship):
            extra = (
                {"page_loader": object, "page_capability": _capability()}
                if cls is RemotePagedRelationship
                else {}
            )
            with pytest.raises(TypeError):  # loader missing
                cls(
                    name="x", direction="ONETOMANY", fk_field="x_id",
                    target_entity=object, is_list=True, **extra,
                )


def _capability():
    from nexusx.loader.pagination import BatchPageCapability

    return BatchPageCapability(default_order="PRIMARY", orders=[])


class TestLoaderAccessors:
    """loader_classes() / plain_loader_of() / page_capability_of() replace the
    20 ``getattr(rel, "loader", None)`` reads the review found (#160 DESIGN_5)."""

    def test_loader_classes_expectation_table(self):
        local_plain = LocalRelationship(
            name="a", direction="ONETOMANY", fk_field="id", target_entity=object,
            is_list=True, loader=int,
        )
        local_paged = LocalRelationship(
            name="a", direction="ONETOMANY", fk_field="id", target_entity=object,
            is_list=True, loader=int, page_loader=str, sort_field="id",
        )
        remote_plain = RemotePlainRelationship(
            name="a", direction="MANYTOONE", fk_field="id", target_entity=object,
            is_list=False, loader=int,
        )
        remote_paged = RemotePagedRelationship(
            name="a", direction="ONETOMANY", fk_field="id", target_entity=object,
            is_list=True, loader=int, page_loader=str, page_capability=_capability(),
        )
        coalesced = RemoteCoalescedRelationship(
            name="a", direction="ONETOMANY", fk_field="id", target_entity=object,
            is_list=True,
        )
        assert local_plain.loader_classes() == (int,)
        assert local_paged.loader_classes() == (int, str)
        assert remote_plain.loader_classes() == (int,)
        assert remote_paged.loader_classes() == (int, str)
        assert coalesced.loader_classes() == ()

        assert plain_loader_of(local_paged) is int
        assert plain_loader_of(remote_paged) is int
        assert plain_loader_of(coalesced) is None

        assert page_capability_of(remote_paged) is remote_paged.page_capability
        assert page_capability_of(local_paged) is None
        assert page_capability_of(coalesced) is None
        assert page_capability_of(remote_plain) is None

    def test_batch_page_capability_keeps_its_wire_import_path(self):
        """federation.contract re-exports the class that now lives next to
        the loaders; the fragment JSON must not notice the move (§二.2)."""
        from nexusx.federation.contract import BatchPageCapability as ViaContract
        from nexusx.loader.pagination import BatchPageCapability

        assert ViaContract is BatchPageCapability
        assert BatchPageCapability.model_json_schema()["properties"].keys() == {
            "protocol", "default_order", "orders",
        }

    def test_direction_is_a_literal_with_the_historical_values(self):
        from typing import get_args

        from nexusx.loader.registry import RelationshipDirection

        assert set(get_args(RelationshipDirection)) == {
            "MANYTOONE", "ONETOMANY", "ONETOMANY_SCALAR", "MANYTOMANY", "CUSTOM",
        }


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
