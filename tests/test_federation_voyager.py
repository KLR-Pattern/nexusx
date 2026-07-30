"""US4 — Voyager renders the federated graph with ownership tags (FR-016).

Materialized remote types must render as REAL entities (their table lives in
another service), tagged with the owning SERVICE, in a dashed per-service
cluster — NOT as virtual entities. Genuine virtual entities (plain BaseModel,
no table) must keep rendering as virtual. See specs/004 (virtual) + specs/012
FR-016 (federation ownership).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder
from tests.test_federation_e2e import _build_catalog_and_transport


class _GenuineVirtual(BaseModel):
    """Plain BaseModel with no table — a genuine virtual entity (spec 004)."""

    label: str = ""


@pytest.mark.asyncio
async def test_voyager_includes_and_tags_federated_nodes():
    catalog_handler, _transport, client = await _build_catalog_and_transport()
    try:
        er = catalog_handler._er_manager
        builder = ErDiagramDotBuilder(er, show_module=True)
        builder.analysis()

        names = {n.name for n in builder.node_set.values()}
        # Local + materialized remote types all appear.
        assert "FedProduct" in names
        assert "FedReview" in names  # remote (materialized)

        by_name = {n.name: n for n in builder.node_set.values()}

        # The federated node is tagged with its owning SERVICE (FR-016) and is a
        # REAL entity — federated, not virtual.
        review = by_name["FedReview"]
        assert review.module == "reviews"
        assert review.is_federated is True
        assert review.is_virtual is False

        # Local type keeps its real Python module; neither virtual nor federated.
        product = by_name["FedProduct"]
        assert product.module != "reviews"
        assert product.is_federated is False
        assert product.is_virtual is False

        # Render: federated service clusters are dashed (mark the boundary);
        # the local cluster stays rounded.
        dot = builder.render_dot()
        assert 'style="rounded,dashed"' in dot
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_genuine_virtual_stays_virtual_alongside_federated():
    """Regression for the ``and not fed_qn`` carve-out.

    A genuine virtual entity (plain BaseModel, no table) registered via
    ``add_virtual_entities`` must stay virtual — the carve-out must NOT turn it
    federated, nor let a federated type leak into the virtual cluster.
    """
    catalog_handler, _transport, client = await _build_catalog_and_transport()
    try:
        er = catalog_handler._er_manager
        er.add_virtual_entities([_GenuineVirtual])

        builder = ErDiagramDotBuilder(er, show_module=True)
        builder.analysis()
        by_name = {n.name: n for n in builder.node_set.values()}

        # Genuine virtual stays virtual, is not federated.
        virtual = by_name["_GenuineVirtual"]
        assert virtual.is_virtual is True
        assert virtual.is_federated is False

        # Federated type is still real (not virtual), still federated.
        assert by_name["FedReview"].is_virtual is False
        assert by_name["FedReview"].is_federated is True

        # Render: the genuine virtual lands in cluster_virtual; the federated
        # service cluster is dashed — the two groups stay visually distinct.
        dot = builder.render_dot()
        assert "cluster_virtual" in dot
        assert 'style="rounded,dashed"' in dot
    finally:
        await client.aclose()
