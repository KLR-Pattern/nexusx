"""specs/016 — mounter DefineSubset 字段注解含 RemoteRef 的延迟解析。

mounter 端 `ProductDTO.reviews: list[reviews.ReviewDTO]`（member public DTO）：
source 是本地实体（Product），但 extra 字段注解含 RemoteRef。SubsetMeta 必须在
create_model 时把该字段占位为 Any（否则 PydanticSchemaGenerationError），并把
raw 注解登记为 deferred；federate 物化 member DTO 后，resolve_remote_field_refs
把占位替换成物化 DTO 类 + model_rebuild。

注意：字段名不能与服务命名空间变量同名（Python 类体名字遮蔽），故测试用别名服务。
"""

from pydantic import Field
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from nexusx import DefineSubset
from nexusx.federation import RemoteService
from nexusx.federation.contract import EntityFragment, FieldDescriptor
from nexusx.federation.registry import FederatedTypeRegistry
from nexusx.federation.remote_ref import resolve_remote_field_refs

# 别名服务：字段名 `reviews` ≠ 命名空间变量 `rev_svc`，避免类体遮蔽。
rev_svc = RemoteService("reviews", url="http://test/reviews")


class _DeferBase(SQLModel):
    pass


class _DeferProduct(_DeferBase, table=True):
    __tablename__ = "dto_defer_product"
    id: int | None = SQLField(default=None, primary_key=True)
    name: str


def test_define_subset_with_remote_ref_field_creates_deferred():
    """含 RemoteRef 的 extra 字段：类可创建，字段被占位 + 登记 raw 注解。"""

    class ProductDTO(DefineSubset):
        __subset__ = (_DeferProduct, ("id", "name"))
        reviews: list[rev_svc.ReviewDTO] = Field(default_factory=list)

    # 类成功创建
    assert ProductDTO.__name__ == "ProductDTO"
    assert set(ProductDTO.model_fields) >= {"id", "name", "reviews"}
    # raw RemoteRef 注解被登记
    refs = getattr(ProductDTO, "__nexusx_remote_field_refs__", None)
    assert refs and "reviews" in refs


def test_resolve_remote_field_refs_swaps_placeholder_for_materialized():
    """federate 物化 member DTO 后，resolve 把占位字段换成物化 DTO 类。"""

    class ProductDTO(DefineSubset):
        __subset__ = (_DeferProduct, ("id", "name"))
        reviews: list[rev_svc.ReviewDTO] = Field(default_factory=list)

    # member 物化一个 ReviewDTO 类（qualified "reviews.ReviewDTO"）
    reg = FederatedTypeRegistry()
    reg.materialize({
        "reviews.ReviewDTO": EntityFragment(
            typename="ReviewDTO",
            scalar_fields=[
                FieldDescriptor(name="title", type_name="str"),
                FieldDescriptor(name="rating", type_name="int"),
            ],
        )
    })
    materialized = reg.get("reviews.ReviewDTO")

    resolve_remote_field_refs(reg)

    anno = ProductDTO.model_fields["reviews"].annotation
    # list[ReviewDTO_materialized]（可能带 | None 不带，看占位默认）
    assert materialized in _flatten_types(anno), (
        f"expected materialized ReviewDTO in {anno!r}"
    )

    # 实例化 + 赋值能装物化 DTO 实例
    inst = ProductDTO(id=1, name="x")
    inst.reviews = [materialized(title="t", rating=5)]
    assert inst.reviews[0].title == "t"


def test_resolve_skips_unmounted_refs():
    """RemoteRef 指向未被本 fed_registry mount 的服务 → 跳过（多 app 共存）。"""

    class ProductDTO(DefineSubset):
        __subset__ = (_DeferProduct, ("id", "name"))
        reviews: list[rev_svc.ReviewDTO] = Field(default_factory=list)

    reg = FederatedTypeRegistry()  # 空，不含 reviews.ReviewDTO
    resolve_remote_field_refs(reg)  # 不应抛
    # 字段仍未解析（占位保留）——只要不崩即可
    assert "reviews" in ProductDTO.model_fields


def _flatten_types(anno):
    """把注解里所有 type 对象摊平成集合（list[X] → {list, X}）。"""
    import typing

    out = set()
    origin = typing.get_origin(anno)
    if origin is not None:
        out.add(origin)
        for a in typing.get_args(anno):
            out |= _flatten_types(a)
    elif isinstance(anno, type):
        out.add(anno)
    return out
