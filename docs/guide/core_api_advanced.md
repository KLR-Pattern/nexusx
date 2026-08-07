# Core API Advanced

Implicit auto-loading handles most cases: declare a field, name it after a relationship, and it loads. But what about fields that don't match a relationship? Or derived values that depend on already-loaded data? Or parent-child coordination?

This page covers three progressive capabilities: **`resolve_*` → `post_*` → Cross-layer data flow**.

## Step 1: `resolve_*` — Custom Loading

When the field name doesn't match a relationship, or you need custom loading logic, write a `resolve_*` method:

```python
from nexusx import Loader

async def comments_loader(task_ids: list[int]) -> list[list[Comment]]:
    """Batch load comments for multiple tasks."""
    ...

class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title", "owner_id"))
    owner: UserDTO | None = None          # Implicit — matches Task.owner
    comments: list[CommentDTO] = []       # Custom — no matching relationship
    comment_count: int = 0

    def resolve_comments(self, loader=Loader(comments_loader)):
        return loader.load(self.id)
```

### Two ways to use Loader

```python
# Pass a DataLoader class
def resolve_tags(self, loader=Loader(TagLoader)):
    return loader.load(self.id)

# Pass an async batch function
async def load_permissions(user_ids):
    ...
def resolve_permissions(self, loader=Loader(load_permissions)):
    return loader.load(self.owner_id)
```

!!! tip
    Mental model: `resolve_*` means "this field needs data from outside the current node". If the field name already matches a registered relationship, you don't need it — implicit auto-loading handles it.

## Step 2: `post_*` — Computed Fields After Loading

`post_*` runs **after** all `resolve_*` and auto-loading in the current subtree is complete. Use it for counting, aggregation, formatting — anything that depends on already-loaded data:

```python
class SprintDTO(DefineSubset):
    __subset__ = (Sprint, ("id", "name"))
    tasks: list[TaskDTO] = []
    task_count: int = 0
    contributor_names: list[str] = []

    def post_task_count(self):
        return len(self.tasks)

    def post_contributor_names(self):
        return sorted({t.owner.name for t in self.tasks if t.owner})
```

### Execution order

1. Auto-loading → `tasks` populated with TaskDTO list
2. Each TaskDTO → Auto-loading → `owner` populated
3. `post_task_count` → `len(self.tasks)`
4. `post_contributor_names` → Deduplicated owner names

### When to use which

| | `resolve_*` | `post_*` |
|---|---|---|
| Needs external IO? | Yes | Usually not |
| Are descendants ready? | No | Yes |
| Good for counting, summing? | Sometimes | Yes |
| Return value continues resolving? | Yes | No |

## Step 3: Cross-layer Data Flow

When parent and child nodes need to cooperate across tree levels — ancestor context flowing down, or descendant values aggregating up.

### ExposeAs: Ancestor → Descendant

Pass data down the tree:

```python
from typing import Annotated
from nexusx import ExposeAs

class SprintDTO(DefineSubset):
    __subset__ = (Sprint, ("id", "name"))
    name: Annotated[str, ExposeAs('sprint_name')]  # Expose to descendants
    tasks: list[TaskDTO] = []

class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title", "owner_id"))
    full_title: str = ""

    def post_full_title(self, ancestor_context):
        return f"{ancestor_context['sprint_name']} / {self.title}"
```

### SendTo + Collector: Descendant → Ancestor

Aggregate values up the tree:

```python
from nexusx import SendTo, Collector

class SprintDTO(DefineSubset):
    __subset__ = (Sprint, ("id", "name"))
    tasks: list[TaskDTO] = []
    contributors: list[UserDTO] = []

    def post_contributors(self, collector=Collector('contributors')):
        return collector.values()  # Collect values sent by descendants

class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title", "owner_id"))
    owner: Annotated[UserDTO | None, SendTo('contributors')] = None  # Send to ancestor
```

!!! tip
    Use cross-layer data flow when child nodes need ancestor context (sprint name, permissions, tenant config) or when parent nodes need to aggregate values from descendants (contributors, tags). If you don't need tree-level coordination, `resolve_*` and `post_*` are enough.

## Resolver Options

```python
result = await Resolver(
    context={"user_id": 42},
    loader_instances={PermissionLoader: primed_loader},
).resolve(dtos)
```

Declare `context` explicitly on a resolver method to receive request-scoped
values:

```python
def resolve_permissions(self, context):
    return load_permissions(context["user_id"], self.id)
```

`loader_instances` supplies existing DataLoader objects to matching
`Loader(PermissionLoader)` declarations, which is useful for primed caches or
loaders with constructor state. It does not affect implicit relationship
auto-loading.

Do not confuse `context` with `ancestor_context`: request context comes from
`Resolver(context=...)`, while ancestor context is built only from fields
marked with `ExposeAs`.

## Recap

- `resolve_*` loads data from outside the current node — use it when implicit auto-loading doesn't apply
- `post_*` computes derived fields after all descendants are resolved — counting, aggregation, formatting
- `ExposeAs` sends ancestor data down; `SendTo` + `Collector` aggregates descendant data up
- Only use cross-layer data flow when the tree structure truly matters

## Next Steps

- [Custom Relationships](./custom_relationship.md) — Non-ORM relationship declarations
- [MCP Service](../advanced/mcp_service.md) — Expose APIs to AI agents
