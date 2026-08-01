"""US5 — federated schema rendering (SDL + __schema introspection).

FR-017: SDL/Introspection are registry-driven, so remote materialized types and
cross-service relationship fields appear in the client-facing schema (bare
names, no service prefix). Reuses the module-level federation setup from
test_federation_e2e (single class registration → no global clsregistry clashes).
"""

from __future__ import annotations

import pytest

# Importing from a sibling test module reuses its module-level entities + engines
# (defined once → no duplicate class-registration in SQLAlchemy's global registry).
from tests.test_federation_e2e import _build_catalog_and_transport


@pytest.mark.asyncio
async def test_sdl_contains_remote_type_and_field_bare_names():
    catalog_handler, _transport, client = await _build_catalog_and_transport()
    try:
        sdl = catalog_handler.get_sdl(include_mutations=False)
        # Remote materialized type appears, bare name (no "reviews." prefix).
        assert "type FedReview {" in sdl
        assert "reviews.FedReview" not in sdl
        # Cross-service relationship field on the local type, bare target.
        assert "reviews: [FedReview!]!" in sdl
        # Remote type's scalar fields rendered.
        review_block = sdl[sdl.index("type FedReview {"):]
        assert "title" in review_block
        assert "rating" in review_block
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_introspection_contains_remote_type_and_field():
    catalog_handler, _transport, client = await _build_catalog_and_transport()
    try:
        intro = catalog_handler.get_introspection_data()
        types = {t["name"]: t for t in intro["types"]}
        assert "FedReview" in types
        assert "reviews.FedReview" not in types  # bare name only

        # FedProduct has the remote `reviews` field pointing at FedReview.
        product = types["FedProduct"]
        field_map = {f["name"]: f for f in product["fields"]}
        assert "reviews" in field_map
        type_names = _collect_type_names(field_map["reviews"]["type"])
        assert "FedReview" in type_names
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_render_matches_registry_relationships():
    """SC-007 parity: SDL relationship fields = registry relationships, per type."""
    catalog_handler, _transport, client = await _build_catalog_and_transport()
    try:
        sdl = catalog_handler.get_sdl(include_mutations=False)
        er = catalog_handler._er_manager

        # FedProduct: registry has `reviews`; SDL must list it.
        product = next(e for e in catalog_handler.entities if e.__name__ == "FedProduct")
        product_rels = set(er.get_relationships(product).keys())
        assert "reviews" in product_rels
        product_block = sdl[sdl.index("type FedProduct {"):sdl.index("type FedProduct {") + 200]
        for rel in product_rels:
            assert rel in product_block
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_introspection_query_path_shows_federated_types():
    """Introspection via the QUERY path (execute → executor → __schema).

    GraphiQL POSTs an introspection query, which goes through the executor's
    introspection_generator — NOT get_introspection_data(). After federate()
    rebuilds the handler's generator, the executor must be re-pointed at it,
    else the query path serves the stale pre-federate generator and federated
    types/fields vanish (regression: reviews rendered as [String!]!).
    """
    catalog_handler, _transport, client = await _build_catalog_and_transport()
    try:
        res = await catalog_handler.execute(
            "{ __schema { types { name fields { name type { name kind "
            "ofType { name kind ofType { name } } } } } } }"
        )
        assert not res.get("errors"), res
        types = {t["name"]: t for t in res["data"]["__schema"]["types"]}
        assert "FedReview" in types
        review = types["FedReview"]
        assert "title" in {f["name"] for f in (review.get("fields") or [])}
        # FedProduct.reviews must reference FedReview (not fall back to String).
        product = types["FedProduct"]
        reviews_field = next(f for f in product["fields"] if f["name"] == "reviews")
        assert "FedReview" in _collect_type_names(reviews_field["type"])
    finally:
        await client.aclose()


def _collect_type_names(type_ref: dict) -> set[str]:
    """Walk an introspection type-ref and collect named type names."""
    names: set[str] = set()
    while type_ref:
        if type_ref.get("name"):
            names.add(type_ref["name"])
        type_ref = type_ref.get("ofType")
    return names
