"""specs/019 — paged provider 闭包单测。

验证 ``QueryExecutor._make_paged_provider`` 的闭包正确 merge
(default from RelationshipInfo + gql args override via ``Resolver._merge_paged``):
  - gql limit 覆盖 default
  - rel default order 保留(gql 无 order 时)
  - gql order 覆盖 rel default
  - enum args(order.value/direction.value)解包
  - gql 无 args → rel default Paged

provider 是 019 的核心:gql 知识封装在 executor 注入的闭包里,Resolver 只调它,
不读 field_sel.arguments。
"""

from types import SimpleNamespace

from nexusx.execution.query_executor import QueryExecutor
from nexusx.loader.pagination import Paged
from nexusx.query_parser import FieldSelection


def _provider():
    """Build a provider closure (no executor state — it's stateless)."""
    return QueryExecutor.__new__(QueryExecutor)._make_paged_provider()


def _field_sel(args: dict) -> FieldSelection:
    """Root FieldSelection whose sub-field 'reviews' carries ``args``."""
    reviews = FieldSelection(name="reviews", arguments=args)
    root = FieldSelection(name="root")
    root.sub_fields = {"reviews": reviews}
    return root


def _rel(default_order: str | None = None) -> SimpleNamespace:
    """Fake RelationshipInfo with only the fields _rel_default_paged reads."""
    cap = SimpleNamespace(default_order=default_order) if default_order else None
    return SimpleNamespace(
        page_capability=cap, is_list=True, page_loader=object(),
        default_page_size=20, max_page_size=100,
    )


def test_gql_limit_overrides_default():
    """gql limit=5 + rel no default → effective.limit=5."""
    p = _provider()(_rel(), _field_sel({"limit": 5}), "reviews")
    assert p.limit == 5


def test_rel_default_order_preserved_when_gql_silent():
    """gql silent on order + rel default_order='NEWEST' → effective.order='NEWEST'."""
    p = _provider()(_rel(default_order="NEWEST"), _field_sel({"limit": 5}), "reviews")
    assert p.order == "NEWEST"
    assert p.limit == 5  # gql limit still wins


def test_gql_order_overrides_rel_default():
    """gql order='RATING' overrides rel default_order='NEWEST'."""
    p = _provider()(
        _rel(default_order="NEWEST"), _field_sel({"limit": 5, "order": "RATING"}), "reviews",
    )
    assert p.order == "RATING"


def test_enum_args_unwrapped():
    """gql enum order/direction (objects with .value) → unwrapped to str."""
    class FakeEnum:
        def __init__(self, v):
            self.value = v

    p = _provider()(
        _rel(),
        _field_sel({"order": FakeEnum("RATING"), "direction": FakeEnum("ASC")}),
        "reviews",
    )
    assert p.order == "RATING"
    assert p.direction == "ASC"


def test_no_gql_args_returns_rel_default():
    """gql no args + rel default_order → effective = rel default (limit None)."""
    p = _provider()(_rel(default_order="NEWEST"), _field_sel({}), "reviews")
    assert p.limit is None
    assert p.order == "NEWEST"


def test_provider_returns_paged_instance():
    """Provider always returns a Paged (never None for a paged field)."""
    p = _provider()(_rel(), _field_sel({"limit": 5}), "reviews")
    assert isinstance(p, Paged)
