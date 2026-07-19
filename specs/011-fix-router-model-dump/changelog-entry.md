# CHANGELOG Entry Draft

> 本草稿供 `/release` skill 在版本发布阶段最终落地到 `CHANGELOG.md`。
> 关联 issue: KLR-Pattern/nexusx#107
> 关联 spec: specs/011-fix-router-model-dump/

## 行为变化摘要

**修复前**：`@query` / `@mutation` 方法声明嵌套 BaseModel 参数（如 `items: List[ItemInput]`、`item: ItemInput`、`item: Optional[ItemInput]` 等）时，方法体实际收到的是被 `model_dump()` 拍平的 dict 形态（`List[dict]` / `dict` / `Optional[dict]`），与签名声明的类型契约不一致。这迫使开发者用 `isinstance(it, dict)` 双分支防御性代码访问字段。

**修复后**：方法体收到的参数与签名声明完全一致——嵌套 BaseModel 实例原样保留，`it.text` 属性访问直接可用。

## 受影响的代码模式

**1. 受益（修复后正常工作）**：

```python
@mutation
async def create_items(cls, items: List[ItemInput]) -> List[ItemOutput]:
    return [ItemOutput(text=it.text, checked=it.checked) for it in items]
    #                       ^^^^^^^ 修复前 AttributeError，修复后正常
```

**2. 极少数破坏场景（依赖了 bug 行为的用户代码）**：

```python
@mutation
async def create_items(cls, items: List[ItemInput]) -> ...:
    return [{"text": it["text"]} for it in items]
    #                    ^^^^^^^ 修复前用 dict 访问能"侥幸工作"
    #                            修复后会抛 TypeError（ItemInput 不支持索引）
```

如果你写过这种代码，迁移方法是直接改成属性访问：`it["text"]` → `it.text`。

## 影响范围

- **公共 API 无变化**：`UseCaseService` / `@query` / `@mutation` / `create_router` / `UseCaseAppConfig` 的签名与行为完全不变。
- **Schema 生成无变化**：OpenAPI / compose SDL 输出在修复前后二进制一致（schema 路径与 router 路径正交）。
- **标量参数无变化**：`UUID` / `str` / `int` / `bool` / `datetime` 等标量参数的运行时形态完全一致。
- **FromContext 注入无变化**：`Annotated[T, FromContext()]` 参数依然走 context_extractor 注入路径。
- **默认值无变化**：方法参数的默认值行为完全一致。

## 建议版本号

**patch**（如 3.6.2 → 3.6.3）——这是修复 router 违反签名契约的 bug，行为变化完全符合已声明的类型签名。极少数依赖 bug 行为的用户代码需要迁移，但在 CHANGELOG 中提示即可。

（最终版本号由 `/release` skill 决定，本草稿仅作建议。）

## Draft CHANGELOG Markdown

```markdown
### Fixed

- **router**: 修复 `@query` / `@mutation` 方法的嵌套 BaseModel 参数被错误地以 dict 形态传入方法体的问题（`body.model_dump()` 把已构造的 BaseModel 实例递归拍平）。修复后方法体收到与签名声明完全一致的 BaseModel 实例。标量参数、FromContext 注入、默认值、字段 alias、schema 生成等其他行为完全不变。#107
```
