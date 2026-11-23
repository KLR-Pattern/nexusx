# nexusx 技术实现原理

本文档详细描述 nexusx 项目的转换逻辑和技术实现原理。

## 目录

1. [项目概述](#项目概述)
2. [核心架构](#核心架构)
3. [模块详解](#模块详解)
4. [数据流转换](#数据流转换)
5. [类型系统](#类型系统)
6. [DataLoader 关系解析](#dataloader-关系解析)
7. [Core API 响应构建](#core-api-响应构建)

---

## 项目概述

nexusx 是一个为 SQLModel 提供 GraphQL 支持的库，主要功能：

- **SDL 生成**：从 SQLModel 类自动生成 GraphQL Schema Definition Language
- **查询执行**：执行 GraphQL 查询并返回结果
- **DataLoader 关系解析**：通过 DataLoader 批量加载关联数据，自动避免 N+1 问题
- **分页支持**：列表关系支持 limit/offset 分页
- **Core API 响应构建**：通过 `DefineSubset` + `Resolver` 组装 DTO 树
- **跨层数据流**：通过 `ExposeAs` / `SendTo` / `Collector` 在树中传递上下文
- **自定义关系与 ER 图**：支持非 ORM `Relationship(...)` 和 Mermaid ER 图生成

本文前 6 节聚焦 GraphQL 模式，第 7 节补充 Core API 模式如何复用同一套 LoaderRegistry。

### 核心设计理念

```
SQLModel Entity  →  GraphQL Schema (SDL)
       ↓                    ↓
   @query/@mutation   →  Query/Mutation Type
       ↓                    ↓
   Python Type Hints →  GraphQL Types
       ↓                    ↓
   ORM Relationships →  DataLoader (batch load)
```

---

## 核心架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户代码层                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ SQLModel    │  │ @query      │  │ @mutation               │ │
│  │ Entity      │  │ decorator   │  │ decorator               │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        核心处理层                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ GraphQLHandler  │  │ SDLGenerator    │  │ QueryParser     │ │
│  │ (查询执行)       │  │ (Schema生成)    │  │ (查询解析)       │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐                      │
│  │ Introspection   │  │ TypeConverter   │                      │
│  │ Generator       │  │ (类型转换)       │                      │
│  └─────────────────┘  └─────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     DataLoader 层                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ LoaderRegistry  │  │ DataLoader      │  │ PageLoader      │ │
│  │ (关系注册表)     │  │ Factories       │  │ (ROW_NUMBER)    │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        数据库层                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ SQLAlchemy AsyncSession                                     ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 模块详解

### 1. decorator.py - 装饰器模块

**职责**：将普通方法标记为 GraphQL 查询或变更操作。

#### 转换逻辑

```
Python 方法                         →    GraphQL Field（按实体分组）
──────────────────────────────────────────────────────────────────────
User.get_all  +  @query             →    type UserQuery { get_all(...): ... }
                                         type Query { User: UserQuery! }
User.create   +  @mutation          →    type UserMutation { create(...): ... }
                                         type Mutation { User: UserMutation! }
```

#### 装饰器用法

```python
@query
async def get_all(cls, limit: int = 10) -> list['User']: ...
```

- 只有一种风格：`@query` / `@mutation` 直接装饰 classmethod，不带参数。
- 方法名**原样**作为字段名（不做 camelCase、不加实体前缀）；描述取自 docstring。
- 同一实体的方法挂在 `{Entity}Query` / `{Entity}Mutation` 分组类型上，根 `Query` 每个实体一个挂载字段。

---

### 2. type_converter.py - 类型转换器

**职责**：统一处理 Python 类型到 GraphQL 类型的转换逻辑。

#### 核心转换映射

```
Python 类型          →    GraphQL 类型
─────────────────────────────────────────
int                 →    Int
str                 →    String
bool                →    Boolean
float               →    Float
Optional[T]         →    T (nullable)
list[T]             →    [T!]!
Entity类            →    Entity (Object)
Enum类              →    Enum
Mapped[T]           →    T (unwrap)
```

---

### 3. sdl_generator.py - SDL 生成器

**职责**：从 SQLModel 类生成 GraphQL Schema Definition Language。

#### 生成流程

```
SQLModel Entity
       │
       ├── model_fields → 标量字段（排除 FK 字段）
       │      │
       │      └── _field_info_to_graphql() → "fieldName: String!"
       │
       ├── type_hints → 关系字段
       │      │
       │      └── _type_hint_to_graphql() → "posts: PostResult!"
       │         （分页启用时生成 Result 类型）
       │
       └── @query/@mutation 方法
              │
              └── _method_to_graphql_field() → "users(limit: Int): [User!]!"
```

---

### 4. query_parser.py - 查询解析器

**职责**：解析 GraphQL 查询，提取字段选择树用于关系解析。

#### 解析流程

```
GraphQL Query
       │
       │  parse()
       ↓
{
  'User': FieldSelection(
    name='User',
    sub_fields={
      'get_all': FieldSelection(
        name='get_all',
        arguments={'limit': 5},
        sub_fields={
          'id': FieldSelection(name='id'),
          'name': FieldSelection(name='name'),
          'posts': FieldSelection(
            name='posts',
            arguments={'limit': 3},
            sub_fields={
              'items': FieldSelection(
                sub_fields={'title': FieldSelection(name='title')}
              ),
              'pagination': FieldSelection(
                sub_fields={'has_more': ..., 'total_count': ...}
              )
            }
          )
        }
      )
    }
  )
}
```

---

### 5. loader/ - DataLoader 模块

**职责**：从 ORM 元数据自动发现关系，创建对应的 DataLoader 批量加载器。

#### 模块结构

```
loader/
├── __init__.py       # 导出
├── registry.py       # 关系注册表 (LoaderRegistry)
├── factories.py      # DataLoader 工厂函数
└── pagination.py     # 分页类型定义
```

#### ErManager（关系注册表）

```python
class ErManager:
    """检查 ORM 元数据，为每个关系创建 DataLoader。"""

    def __init__(self, session_factory, *, base=None, entities=None, ...):
        # base= 自动发现子类；entities= 显式列表（二者互斥）
        for entity in entities:
            rels = _inspect_relationships(entity, all_entities, session_factory)
            # rels 包含 MANYTOONE, ONETOMANY, MANYTOMANY 关系信息
```

分页能力是**声明**出来的：关系上写了 `order_by`（`sa_relationship_kwargs={"order_by": ...}`）
即装配 `page_loader`，没有全局开关。

#### 关系发现

```
SQLModel Entity (通过 sqlalchemy.inspect)
       │
       ├── MANYTOONE → create_many_to_one_loader
       │
       ├── ONETOMANY
       │   ├── 列表关系 → create_one_to_many_loader
       │   │            + create_page_one_to_many_loader (声明 order_by 时)
       │   └── 标量关系 → create_many_to_one_loader
       │
       └── MANYTOMANY → create_many_to_many_loader
                      + create_page_many_to_many_loader (声明 order_by 时)
```

---

### 6. handler.py - GraphQL 处理器

**职责**：协调各组件，执行 GraphQL 查询。

#### 执行流程

```
GraphQL Query String
         │
         │  execute()
         ↓
┌────────────────────────────────┐
│ 1. 检测是否为内省查询           │
│    (__schema, __type)          │
└────────────────────────────────┘
         │
    ┌────┴────┐
    ↓         ↓
 内省查询    普通查询
    │         │
    ↓         ↓
┌────────┐  ┌────────────────────────────┐
│Introsp-│  │ 2. QueryParser.parse()     │
│ection  │  │    提取 SelectionTree      │
│Generator│  └────────────────────────────┘
└────────┘              │
                        ↓
           ┌────────────────────────────┐
           │ 3. 查找对应的 @query 方法   │
           │    执行用户方法             │
           │    (只加载标量字段)         │
           └────────────────────────────┘
                        │
                        ↓
           ┌────────────────────────────┐
           │ 4. resolve_relationships   │
           │    逐层 DataLoader 批量加载 │
           │    (支持嵌套关系)           │
           └────────────────────────────┘
                        │
                        ↓
           ┌────────────────────────────┐
           │ 5. 序列化结果              │
           │    按请求字段输出           │
           └────────────────────────────┘
                        │
                        ↓
              GraphQL Response
```

---

## 数据流转换

### 完整查询流程示例

```
1. 客户端发送查询
─────────────────────────────────────────────────────────────
POST /graphql
{
  "query": "{ User { get_all(limit: 2) { id name posts(limit: 3) { items { title } } } } }"
}

2. QueryParser 解析选择树
─────────────────────────────────────────────────────────────
{
  'User': FieldSelection(
    sub_fields={
      'get_all': FieldSelection(arguments={'limit': 2}, sub_fields={
        'id': ..., 'name': ...,
        'posts': FieldSelection(arguments={'limit': 3}, sub_fields={
          'items': FieldSelection(sub_fields={'title': ...})
        })
      })
    }
  )
}

3. 执行 @query 方法（只加载标量字段）
─────────────────────────────────────────────────────────────
method = User.get_all
args = {'limit': 2}
result = [User(id=1, name="Alice"), User(id=2, name="Bob")]
# 注意：posts 字段未加载

4. 第一层关系解析：posts
─────────────────────────────────────────────────────────────
# 收集所有父实体的 FK 值
fk_values = [user.id for user in users]  # [1, 2]

# DataLoader 批量加载
loader = get_loader(Post_O2M_loader)
# SQL: SELECT post.* FROM post WHERE post.author_id IN (1, 2)

# 分页（关系声明了 order_by 时使用 ROW_NUMBER）
page_loader = get_loader(Post_PO2M_loader)
# SQL: SELECT * FROM (
#   SELECT *, ROW_NUMBER() OVER (PARTITION BY author_id ORDER BY id) AS _rn
#   FROM post WHERE author_id IN (1, 2)
# ) WHERE _rn BETWEEN 1 AND 4

5. 序列化响应
─────────────────────────────────────────────────────────────
{
  "data": {
    "User": {
      "get_all": [
        {"id": 1, "name": "Alice", "posts": {"items": [{"title": "Hello"}]}},
        {"id": 2, "name": "Bob", "posts": {"items": [{"title": "Tips"}]}}
      ]
    }
  }
}
```

---

## 类型系统

### Python → GraphQL 类型映射

```
┌────────────────────────────────────────────────────────────┐
│ Python 类型                 │ GraphQL 类型                  │
├────────────────────────────────────────────────────────────┤
│ int                        │ Int                          │
│ str                       │ String                       │
│ bool                      │ Boolean                      │
│ float                     │ Float                        │
│ Optional[int]             │ Int                          │
│ list[int]                 │ [Int!]!                      │
│ list[User] (Entity)       │ [User!]! 或 UserResult!      │
│ Optional[User]            │ User                         │
│ Status (Enum)             │ Status!                      │
└────────────────────────────────────────────────────────────┘
```

### 分页 Result 类型（关系声明 order_by 时）

```graphql
type Pagination {
  has_more: Boolean!
  total_count: Int
}

type PostResult {
  items: [Post!]!
  pagination: Pagination!
}
```

声明了 `order_by` 的列表关系字段渲染为 `EntityResult!` 类型，并接受 `limit`、`offset`、`fetchAll` 参数。
量意图是必填的：必须传 `limit` 或 `fetchAll: true`（没有默认页大小；`fetchAll` 覆盖 `limit`/`offset`）。

---

## DataLoader 关系解析

### N+1 问题的解决

```python
# 未优化的查询（N+1）
users = await session.exec(select(User))
for user in users:
    # 每次循环都查询一次 posts - N+1 问题！
    posts = await session.exec(select(Post).where(Post.author_id == user.id))
```

### DataLoader 批量加载方案

```
优化后 (DataLoader):
─────────────────────────────────────
# 第1层：加载根实体
SELECT user.* FROM user LIMIT 10;             -- 1 次

# 第2层：批量加载所有 posts（按 author_id IN 批量查询）
SELECT post.* FROM post
WHERE post.author_id IN (1,2,...,10);          -- 1 次

# 如果有更深的关系（如 comments），继续批量加载
SELECT comment.* FROM comment
WHERE comment.post_id IN (1,2,...,30);          -- 1 次
─────────────────────────────────────
总计: 3 次数据库查询（每层一次）
```

### 分页实现

列表关系使用 `ROW_NUMBER()` 窗口函数实现高效的 per-parent 分页：

```sql
SELECT * FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY fk_col ORDER BY sort_col) AS _rn,
           COUNT(*) OVER (PARTITION BY fk_col) AS _tc
    FROM target_table
    WHERE fk_col IN (:fk_values)
) sub WHERE _rn BETWEEN :start AND :end
```

一次查询即可为所有父实体获取各自的分页数据。

---

## Core API 响应构建

Core API 模式复用同一套 `LoaderRegistry` 和 DataLoader，但输出目标从 GraphQL
响应切换为 DTO 树，适合 FastAPI REST 接口、服务层编排和非 GraphQL 用例。

### 关键模块

- **subset.py**：`DefineSubset` / `SubsetConfig`，从 SQLModel 实体定义独立 DTO
- **resolver.py**：`Resolver` / `Loader` / `AutoLoad`，负责遍历 DTO 树并执行 `resolve_*` / `post_*`
- **context.py**：`ExposeAs` / `SendTo` / `Collector`，负责跨层上下文和聚合
- **relationship.py**：声明非 ORM `Relationship(...)`，接入手写批量 loader
- **er_diagram.py**：基于 SQLAlchemy 元数据和自定义关系生成 Mermaid ER 图

### 执行流程

```
SQLModel Entity         →     DefineSubset DTO
   ↓                               ↓
 LoaderRegistry         →   Resolver 遍历 DTO 树
   ↓                               ↓
 DataLoader 批量加载     →   resolve_* / AutoLoad / post_*
                 ↓
            ExposeAs / SendTo / Collector
```

### Core API 与 GraphQL 的关系

- GraphQL 模式：入口是 `GraphQLHandler.execute()`，输出 GraphQL 响应字典
- Core API 模式：入口是 `Resolver.resolve()`，输出已填充好的 DTO / DTO 列表
- 两种模式共享 `LoaderRegistry`、DataLoader 批量加载和关系发现逻辑
- Core API 模式额外支持 `post_*` 派生字段、跨层上下文和自定义非 ORM 关系

---

## 总结

nexusx 通过以下核心技术实现 GraphQL 支持：

1. **装饰器标记**：使用 `@query`/`@mutation` 装饰器声明 GraphQL 操作
2. **类型转换**：`TypeConverter` 统一处理 Python → GraphQL 类型映射
3. **Schema 生成**：`SDLGenerator` 从 SQLModel 类生成 GraphQL SDL
4. **查询解析**：`QueryParser` 从 GraphQL 查询提取选择树
5. **关系解析**：`LoaderRegistry` + `DataLoader` 批量加载关联数据
6. **分页支持**：`ROW_NUMBER()` 窗口函数实现 per-parent 分页
7. **内省支持**：`IntrospectionGenerator` 支持 GraphiQL 等工具
8. **DTO 构建**：`DefineSubset` + `Resolver` 组装 GraphQL 之外的响应对象
9. **上下文流转**：`ExposeAs` / `SendTo` / `Collector` 处理树形上下文
10. **扩展关系**：自定义 `Relationship(...)` 和 `ErDiagram` 支持非 ORM 场景

这种设计实现了：
- **声明式 API**：用户只需关注业务逻辑，不需要处理关系加载
- **自动优化**：DataLoader 批量加载避免 N+1 查询问题
- **类型安全**：完整的类型映射和验证
- **工具兼容**：同时支持标准 GraphQL 工具链和 Core API 响应构建
