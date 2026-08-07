# Core API 进阶

当隐式自动加载不够用时，Core API 提供三个递进的能力：`resolve_*` 自定义加载、`post_*` 派生字段计算、跨层数据流。

## `resolve_*`：自定义加载

当字段名不匹配关系，或需要自定义逻辑时，使用 `resolve_*`：

```python
from nexusx import Loader

async def comments_loader(task_ids: list[int]) -> list[list[Comment]]:
    """批量加载多个 task 的 comments。"""
    ...

class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title", "owner_id"))
    owner: UserDTO | None = None          # 隐式——匹配 Task.owner
    comments: list[CommentDTO] = []       # 自定义——无匹配关系
    comment_count: int = 0

    def resolve_comments(self, loader=Loader(comments_loader)):
        """通过自定义批量函数加载 comments。"""
        return loader.load(self.id)
```

`Loader` 接受两种形式：

```python
# DataLoader 类
def resolve_tags(self, loader=Loader(TagLoader)):
    return loader.load(self.id)

# 异步批量函数
async def load_permissions(user_ids):
    ...
def resolve_permissions(self, loader=Loader(load_permissions)):
    return loader.load(self.owner_id)
```

!!! tip
    心智模型：`resolve_*` 的含义就是"这个字段需要从当前节点之外拿数据"。如果字段名已经匹配了已注册的关系，你就不需要它——隐式自动加载会处理。

## `post_*`：派生字段

`post_*` 在当前子树**所有** `resolve_*` 和自动加载完成后执行。用于计数、聚合、格式化——任何依赖已加载数据的计算。

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

执行顺序：

1. 隐式自动加载 → `tasks` 填充 TaskDTO 列表
2. 每个 TaskDTO → 隐式自动加载 → `owner` 填充
3. `post_task_count` → `len(self.tasks)`
4. `post_contributor_names` → 提取去重的 owner 名称

### `resolve_*` vs `post_*`

| 问题 | `resolve_*` | `post_*` |
|------|-------------|----------|
| 需要外部 IO？ | 是 | 通常不需要 |
| 后代节点已就绪？ | 没有 | 是 |
| 适合计数、求和、格式化？ | 有时 | 非常适合 |
| 返回值继续被递归 resolve？ | 会 | 不会 |

## 跨层数据流

当父节点和子节点需要跨树层级协作时使用。只有在树结构确实重要时才需要。

### ExposeAs：祖先 → 后代

```python
from typing import Annotated
from nexusx import ExposeAs

class SprintDTO(DefineSubset):
    __subset__ = (Sprint, ("id", "name"))
    name: Annotated[str, ExposeAs('sprint_name')]  # 暴露给后代
    tasks: list[TaskDTO] = []
```

### SendTo + Collector：后代 → 祖先

```python
from nexusx import SendTo, Collector

class SprintDTO(DefineSubset):
    __subset__ = (Sprint, ("id", "name"))
    name: Annotated[str, ExposeAs('sprint_name')]
    tasks: list[TaskDTO] = []
    contributors: list[UserDTO] = []

    def post_contributors(self, collector=Collector('contributors')):
        return collector.values()  # 收集后代发送的值

class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title", "owner_id"))
    owner: Annotated[UserDTO | None, SendTo('contributors')] = None  # 发送到祖先
    full_title: str = ""

    def post_full_title(self, ancestor_context):
        return f"{ancestor_context['sprint_name']} / {self.title}"
```

!!! tip
    在以下场景使用跨层数据流：子节点需要祖先上下文（sprint 名称、权限信息、租户配置），或父节点需要聚合多个后代的结果（贡献者、标签）。

## Resolver 选项

```python
result = await Resolver(
    context={"user_id": 42},
    loader_instances={PermissionLoader: primed_loader},
).resolve(dtos)
```

在 resolver 方法中显式声明 `context` 参数，才能接收请求级上下文：

```python
def resolve_permissions(self, context):
    return load_permissions(context["user_id"], self.id)
```

`loader_instances` 用于把已有的 DataLoader 实例交给匹配的
`Loader(PermissionLoader)`，适合复用预热缓存或带构造状态的 loader。它不会影响
关系的隐式自动加载。

不要混淆 `context` 和 `ancestor_context`：前者来自 `Resolver(context=...)`，
后者只来自祖先字段上的 `ExposeAs`。

## Loader 依赖名规则

`Loader("author")` 要求 ErManager 中有名为 `author` 的关系。当使用隐式自动加载时通常不需要手写 Loader。

## 回顾

- `resolve_*` 从当前节点之外加载数据——在隐式自动加载不适用时使用
- `post_*` 在所有后代解析完成后计算派生字段
- `ExposeAs` 向下传递数据，`SendTo` + `Collector` 向上聚合数据
- 只在树结构确实重要时才需要跨层数据流

## 下一步

- [自定义关系](./custom_relationship.zh.md) — 非 ORM 关系声明
- [MCP 服务](../advanced/mcp_service.zh.md) — 将 API 暴露给 AI 代理
