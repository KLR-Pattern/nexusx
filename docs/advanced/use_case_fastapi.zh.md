# UseCase + FastAPI

在 FastAPI 中使用同一个 `UseCaseService` 类。路由是薄包装器——业务逻辑留在服务中。

## 路由定义

```python
from fastapi import FastAPI, HTTPException

app = FastAPI()

@app.get("/api/sprints", tags=[SprintService.get_tag_name()])
async def get_sprints():
    return await SprintService.list_sprints()

@app.get("/api/sprints/{sprint_id}", tags=[SprintService.get_tag_name()])
async def get_sprint(sprint_id: int):
    result = await SprintService.get_sprint(sprint_id=sprint_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return result
```

注意路由有多薄——它们只处理参数传递和 HTTP 特有的关注点（比如 404 响应）。所有业务逻辑都在服务类中。

!!! tip
    这就是**薄路由模式**：路由委托给 `UseCaseService` 方法。如果需要改业务逻辑，你只需要改服务——路由不变。

## OpenAPI 分组

`get_tag_name()` 返回类名作为 OpenAPI 兼容的标签名：

```python
SprintService.get_tag_name()  # → "SprintService"
TaskService.get_tag_name()    # → "TaskService"
```

FastAPI 的 `/docs` 页面会按服务标签自动分组路由。

## 架构优势

```
UseCaseService 子类 ──┬── MCP server（AI 代理）
                      └── FastAPI routes（REST API）
```

- **业务逻辑单一定义**：修改只需改一处
- **路由薄包装**：FastAPI 路由只做参数传递和异常处理
- **类型安全**：相同的 DTO 类型在两种模式中复用
- **OpenAPI 自动生成**：FastAPI 自动生成 `openapi.json`，可用于 TypeScript SDK 生成

## 完整示例

```python
from fastapi import FastAPI
from nexusx.use_case import UseCaseService, UseCaseAppConfig, create_use_case_graphql_mcp_server

# 服务定义
class SprintService(UseCaseService):
    @classmethod
    async def list_sprints(cls) -> list[SprintSummary]:
        ...

    @classmethod
    async def get_sprint(cls, sprint_id: int) -> SprintSummary | None:
        ...

# MCP 模式（AI 代理）
mcp = create_use_case_graphql_mcp_server(
    apps=[
        UseCaseAppConfig(name="project", services=[SprintService]),
    ],
    name="Sprint API",
)

# FastAPI 模式（REST API）
app = FastAPI()

@app.get("/api/sprints", tags=[SprintService.get_tag_name()])
async def get_sprints():
    return await SprintService.list_sprints()

@app.get("/api/sprints/{sprint_id}", tags=[SprintService.get_tag_name()])
async def get_sprint(sprint_id: int):
    result = await SprintService.get_sprint(sprint_id=sprint_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return result
```

## 回顾

- 路由是薄包装器，委托给 `UseCaseService` 方法
- `get_tag_name()` 提供 OpenAPI 兼容的标签分组
- 同一个服务类同时服务于 MCP 和 FastAPI，无需重复
- 业务逻辑的修改只需要在一个地方进行

## 下一步

- [UseCase 服务](./use_case_service.zh.md) — UseCaseService 的完整定义方式
- [Core API 模式](../guide/core_api.zh.md) — DTO 定义和 resolve 模式
