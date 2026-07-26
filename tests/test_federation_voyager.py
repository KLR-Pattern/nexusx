"""US4 — Voyager renders the federated graph with ownership tags (FR-016).

Reuses the module-level federation setup from test_federation_e2e (single class
registration). Asserts materialized remote types appear as nodes tagged with
their owning service (qualified name), so the ER diagram shows ownership.
"""

from __future__ import annotations

import pytest

from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder
from tests.test_federation_e2e import _build_catalog_and_transport


@pytest.mark.asyncio
async def test_voyager_includes_and_tags_federated_nodes():
    catalog_handler, _transport, client = await _build_catalog_and_transport()
    try:
        er = catalog_handler._er_manager
        builder = ErDiagramDotBuilder(er)
        builder.analysis()

        names = {n.name for n in builder.node_set.values()}
        # Local + materialized remote types all appear.
        assert "FedProduct" in names
        assert "FedReview" in names  # remote (materialized)

        # The federated node is tagged with its owning service (qualified name).
        review_nodes = [n for n in builder.node_set.values() if n.name == "FedReview"]
        assert review_nodes
        assert review_nodes[0].module == "reviews.FedReview"
        # Local type keeps its real module (not tagged).
        product_nodes = [n for n in builder.node_set.values() if n.name == "FedProduct"]
        assert product_nodes
        assert product_nodes[0].module != "reviews.FedReview"
    finally:
        await client.aclose()
