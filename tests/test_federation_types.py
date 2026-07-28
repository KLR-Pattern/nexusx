"""Type fidelity across federation: lossless type-expression round-trip.

introspect._type_expr renders field annotations as full type-expression strings
(list[str], Optional[int], UUID, enums); FederatedTypeRegistry reconstructs them
exactly via create_model + model_rebuild against a shared type namespace. This
locks that precision (vs the earlier degradation of generics to Any) plus the
unknown-name → Any fallback.
"""

import typing
import uuid

from nexusx.federation.contract import EntityFragment, FieldDescriptor
from nexusx.federation.introspect import _type_expr
from nexusx.federation.registry import FederatedTypeRegistry


def test_type_expr_is_lossless():
    assert _type_expr(int) == "int"
    assert _type_expr(list[str]) == "list[str]"
    assert _type_expr(dict[str, int]) == "dict[str, int]"
    # Optional[X] renders as X | None (round-trips through pydantic)
    assert _type_expr(typing.Optional[int]) == "int | None"  # noqa: UP045
    assert _type_expr(list[str] | None) == "list[str] | None"


def test_materialize_preserves_generics_and_scalars():
    reg = FederatedTypeRegistry()
    reg.materialize({
        "srv.X": EntityFragment(
            typename="X",
            scalar_fields=[
                FieldDescriptor(name="tags", type_name="list[str]"),
                FieldDescriptor(name="scores", type_name="list[int]"),
                FieldDescriptor(name="rid", type_name="UUID"),
                FieldDescriptor(name="maybe", type_name="int | None"),
            ],
        )
    })
    X = reg.get("srv.X")

    tags = str(X.model_fields["tags"].annotation)
    assert "list" in tags and "str" in tags  # generic preserved, not Any
    scores = str(X.model_fields["scores"].annotation)
    assert "list" in scores and "int" in scores
    rid = str(X.model_fields["rid"].annotation)
    assert "UUID" in rid or "uuid" in rid  # scalar preserved

    x = X(tags=["a", "b"], scores=[1, 2], rid=uuid.uuid4(), maybe=5)
    assert x.tags == ["a", "b"]
    assert isinstance(x.rid, uuid.UUID)


def test_unknown_type_falls_back_to_any_with_warning(caplog):
    """A remote enum/custom scalar the mounter hasn't registered → Any + warn."""
    import logging

    reg = FederatedTypeRegistry()
    with caplog.at_level(logging.WARNING, logger="nexusx.federation.registry"):
        reg.materialize({
            "srv.X": EntityFragment(
                typename="X",
                scalar_fields=[
                    FieldDescriptor(name="status", type_name="Status | None"),
                ],
            )
        })
    X = reg.get("srv.X")
    # Did not crash on the unknown name; fell back to Any.
    assert "Status" not in str(X.model_fields["status"].annotation)
    assert any("Status" in r.getMessage() for r in caplog.records)


def test_extra_types_register_custom_types():
    """User-registered types (enums/custom scalars) are materialized precisely."""
    import enum

    class Status(enum.Enum):  # pydantic-compatible custom type
        ACTIVE = "active"
        INACTIVE = "inactive"

    reg = FederatedTypeRegistry(extra_types={"Status": Status})
    reg.materialize({
        "srv.X": EntityFragment(
            typename="X",
            scalar_fields=[FieldDescriptor(name="status", type_name="Status")],
        )
    })
    X = reg.get("srv.X")
    # Resolved to the registered enum, not Any.
    assert "Status" in str(X.model_fields["status"].annotation)
