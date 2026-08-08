# 常见问题

记录使用 nexusx 时容易踩到的几个坑。多数与 SQLModel / Pydantic v2 的交互、或关系加载策略有关。

## UseCaseService 的 URL 路径是怎么生成的？

`UseCaseService` 子类暴露在 `/api/<service_name>/<method_name>`,其中 `service_name` 是**类名的 snake_case 形式**。

```text
ChecklistItemService → /api/checklist_item_service/<method>
SprintService        → /api/sprint_service/<method>
```

注意:**camelCase 的大小写边界**才会被拆分。`Checklist` 内部没有大小写边界,所以整体保留为 `checklist`,而**不会**变成 `check_list`。规则定义在 `use_case/router.py` 的 `_camel_to_snake`。

> 同一规则在 [UseCase Service](../advanced/use_case_service.zh.md) 的 Step 3 也有说明。

## 在 model 实例上 setattr 报错:"X object has no field Y"

**症状**:想把运行时算好的数据挂到 SQLModel 实体上(例如预加载的 M:N 关联):

```python
parent.targets = pre_loaded_list   # ❌ ValueError: "Parent" object has no field "targets"
```

**原因**:Pydantic v2 对 SQLModel 实体强制**严格 schema** —— 只有 model 上声明的字段才能用 `=` 赋值。这是 Pydantic v2 + SQLModel 的交互,不是 nexusx 的 bug。

**做法**:在 `model_validate` 产出 DTO **之后**再赋值;更好的是把数据加载放进 DTO 的 `resolve_*` 方法,交给 Resolver 调度:

```python
# ✅ 方式一:DTO 上赋值
dto = ParentDTO.model_validate(parent)
dto.targets = [TargetDTO.model_validate(t) for t in pre_loaded_list]

# ✅ 方式二(推荐):用 resolve_* + Loader 自动填充
class ParentDTO(DefineSubset):
    __subset__ = SubsetConfig(kls=Parent, fields=["id"])
    targets: list[TargetDTO] = []

    def resolve_targets(self, loader=Loader(TargetLoader)) -> list[TargetDTO]:
        return loader.load(self.id)
```

## 关系用了 lazy="noload",DTO 字段读出来是空?

`lazy="noload"` 是推荐的写性能优化,但该关系不会被 SQLAlchemy 自动加载。nexusx 的纪律是:**Entity 只承载 resource,计算放 DTO** —— 不要依赖 ORM 自动加载关系,而是在 DTO 上用 `resolve_*` + `Loader` 批量填充。

```python
class Parent(SQLModel, table=True):
    id: UUID
    children: list["Child"] = Relationship(
        sa_relationship_kwargs={"lazy": "noload"},  # 性能优化:默认不加载
    )

class ParentDTO(DefineSubset):
    __subset__ = SubsetConfig(kls=Parent, fields=["id"])
    children: list[ChildDTO] = []

    def resolve_children(self, loader=Loader(ChildLoader)) -> list[ChildDTO]:
        # ChildLoader 按 parent_id 批量取数,Resolver 自动调度
        return loader.load(self.id)
```

`Resolver` 会把同一批里所有的 `loader.load(...)` 调用收集起来做批量化(DataLoader 模式),避免 N+1。跨服务的关系同理 —— member 自包含地 resolve 出边,见 [Federation](../advanced/federation.zh.md)。
