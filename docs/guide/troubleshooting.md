# Troubleshooting

Common pitfalls when using nexusx. Most stem from the SQLModel / Pydantic v2 interaction or relationship-loading strategy.

## How is a UseCaseService URL path generated?

A `UseCaseService` subclass is exposed at `/api/<service_name>/<method_name>`, where `service_name` is the **snake_case of the class name**.

```text
ChecklistItemService → /api/checklist_item_service/<method>
SprintService        → /api/sprint_service/<method>
```

Note: only **camelCase case boundaries** are split. `Checklist` has no internal case boundary, so it stays `checklist` and does **not** become `check_list`. The rule lives in `_camel_to_snake` in `use_case/router.py`.

> The same rule is described in Step 3 of [UseCase Service](../advanced/use_case_service.md).

## setattr on a model instance raises "X object has no field Y"

**Symptom**: you want to attach runtime-computed data to a SQLModel entity (e.g. a pre-loaded M:N association):

```python
parent.targets = pre_loaded_list   # ❌ ValueError: "Parent" object has no field "targets"
```

**Cause**: Pydantic v2 enforces **strict schema** on SQLModel instances — only fields declared on the model can be set via `=`. This is a Pydantic v2 + SQLModel interaction, not a nexusx bug.

**Fix**: assign after `model_validate` has produced the DTO; better still, put the data loading in a `resolve_*` method on the DTO and let the Resolver schedule it:

```python
# ✅ Option 1: assign on the DTO
dto = ParentDTO.model_validate(parent)
dto.targets = [TargetDTO.model_validate(t) for t in pre_loaded_list]

# ✅ Option 2 (recommended): resolve_* + Loader
class ParentDTO(DefineSubset):
    __subset__ = SubsetConfig(kls=Parent, fields=["id"])
    targets: list[TargetDTO] = []

    def resolve_targets(self, loader=Loader(TargetLoader)) -> list[TargetDTO]:
        return loader.load(self.id)
```

## A relationship uses lazy="noload" and the DTO field comes back empty

`lazy="noload"` is the recommended write-performance optimization, but the relationship is not auto-loaded by SQLAlchemy. The nexusx discipline is: **entities carry only resources, computation goes in the DTO** — don't rely on ORM auto-loading; fill the field in a `resolve_*` method with a `Loader` instead.

```python
class Parent(SQLModel, table=True):
    id: UUID
    children: list["Child"] = Relationship(
        sa_relationship_kwargs={"lazy": "noload"},  # perf: don't load by default
    )

class ParentDTO(DefineSubset):
    __subset__ = SubsetConfig(kls=Parent, fields=["id"])
    children: list[ChildDTO] = []

    def resolve_children(self, loader=Loader(ChildLoader)) -> list[ChildDTO]:
        # ChildLoader batches by parent_id; the Resolver schedules it
        return loader.load(self.id)
```

The `Resolver` collects every `loader.load(...)` call in the same batch and batches them (DataLoader pattern), avoiding N+1. Cross-service relationships work the same way — the member resolves its own out-edges; see [Federation](../advanced/federation.md).
