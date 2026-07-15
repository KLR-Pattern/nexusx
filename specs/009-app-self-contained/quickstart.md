# Quickstart：业务应用（Application）自包含 端到端验证手册

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md) · **契约**：[contracts/](./contracts/)

> 本文件是**验证手册**，不是实现指南。具体代码改动见 `tasks.md`（由 `/speckit-tasks` 产出）。

---

## 0. 前置条件

- Python ≥ 3.10，`uv` 已安装
- 工作目录在 `/home/tangkikodo/nexusx/`（nexusx 仓库根）
- 安装开发依赖：`uv sync --all-extras`
- 至少能访问 SQLite（demo 用 `aiosqlite`，无需外部数据库）

---

## 1. 单元测试验证

### 1.1 mcp 模块全部测试通过

```bash
uv run pytest tests/mcp/ tests/test_mcp.py tests/test_mcp_schema_enhanced.py -v
```

**预期**：所有测试 PASS；包括：
- 现有 18 个 `test_multi_app_manager.py`（已迁移到 `Application` 形式但语义不变）
- 现有 `test_multi_app_tools.py`（fixture 已迁移）
- 新增 `test_application.py`（构造、所有权、dispose 幂等、URL 脱敏）
- 新增 lifespan/dispose 集成测试

### 1.2 弃用警告验证

```bash
uv run python -W default::DeprecationWarning -c "
from nexusx.mcp import create_mcp_server
from sqlmodel import SQLModel
class B(SQLModel): pass
mcp = create_mcp_server(apps=[{'name': 'x', 'base': B}])
print('OK')
"
```

**预期**：stderr 输出包含 `DeprecationWarning: Passing AppConfig dict is deprecated; use Application(...)`，stdout 输出 `OK`，进程正常退出。

### 1.3 静态检查

```bash
uv run ruff check src/nexusx/mcp/
uv run mypy src/nexusx/mcp/
```

**预期**：零错误。

---

## 2. 端到端验证：多 app 合并（spec 用户故事 1）

### 2.1 启动 demo

```bash
cd demo/multi_app
uv run python -m multi_app.mcp_server
```

**预期**：
- 控制台打印 "Multi-App GraphQL MCP Server"
- 列出 `blog` 与 `shop` 两个 app
- HTTP 服务监听 `0.0.0.0:8004`（默认端口）
- 无报错、无栈追踪

### 2.2 用 mcp client 验证工具

打开另一终端，用任意 mcp client（如 `mcp-cli`、Claude Desktop 配置 streamable-http client）连接 `http://localhost:8004`，依次调用：

| 工具调用 | 预期返回 |
|---|---|
| `list_apps()` | `["blog", "shop"]`（顺序可能不同） |
| `list_queries(app_name="blog")` | blog 应用的查询列表（含 `users`、`posts` 等） |
| `list_queries(app_name="shop")` | shop 应用的查询列表（含 `products`、`orders` 等） |
| `graphql_query(query="{ users { id name } }", app_name="blog")` | blog 数据库里的 user 列表 |
| `graphql_query(query="{ products { id name price } }", app_name="shop")` | shop 数据库里的 product 列表 |
| `graphql_query(query="{ users { id } }", app_name="shop")` | **错误**：blog 的 `users` 不存在于 shop schema |

### 2.3 验证 lifespan dispose

```bash
# 启动 demo 后，找到进程 PID
ps aux | grep multi_app.mcp_server

# 发送 SIGTERM
kill -TERM <PID>
```

**预期**：
- 进程日志中出现 engine dispose 调用记录（如 `[INFO] Disposing engine for app 'blog'` / `'shop'`）
- 进程干净退出（exit code 0）
- 多次 SIGTERM 不抛异常（幂等）

---

## 3. 端到端验证：独立导出 app 包（spec 用户故事 2）

> 本场景验证 spec SC-002：业务应用作为 Python 包发布后，使用者 `pip install` 到首次执行查询仅需配置 1 项（数据库 URL）。

### 3.1 模拟"子项目作为包"

```bash
# 创建临时虚拟环境
uv venv /tmp/test-app-export
source /tmp/test-app-export/bin/activate

# 把 nexusx 自身装上（editable 模式）
cd /home/tangkikodo/nexusx
uv pip install -e ".[fastmcp]"

# 写一段模拟"使用者脚本"——独立项目只 import 一个 app
cat > /tmp/test_app_use.py << 'EOF'
import asyncio
from nexusx.mcp import Application, create_mcp_server
from sqlmodel import SQLModel, Field

# 模拟从某个外部 pip 包 import 进来的 app 单元
class B(SQLModel): pass
class User(B, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str

blog_app = Application(
    name="blog",
    base=B,
    url="sqlite+aiosqlite:////tmp/test_app_use.db",
    description="Blog app from external package",
)

async def main():
    # 独立使用（不挂 mcp server）—— schema 内省
    print("Entities:", blog_app.resources.entity_names)
    print("SDL preview (first 200 chars):")
    print(blog_app.resources.sdl_generator.generate()[:200])

    # 合并到 mcp server
    mcp = create_mcp_server(apps=[blog_app], name="Standalone Test")
    print("MCP server created:", mcp.name)

    # 关闭
    await blog_app.dispose()

asyncio.run(main())
EOF

uv run python /tmp/test_app_use.py
```

**预期**：
- 打印 `Entities: {'User'}`
- 打印 SDL 片段，含 `type User { id: Int! name: String! }` 等
- 打印 `MCP server created: Standalone Test`
- 进程退出无错误；`/tmp/test_app_use.db` 文件被创建（engine 已连过）

### 3.2 验证 schema-only 模式（spec 用户故事 2 验收场景 2）

```bash
cat > /tmp/test_schema_only.py << 'EOF'
from nexusx.mcp import Application
from sqlmodel import SQLModel

class B(SQLModel): pass
class User(B, table=True):
    id: int
    name: str

# 不提供 url/engine/session_factory
app = Application(name="x", base=B)
print("session_factory:", app.session_factory)  # 应为 None
print("Entities:", app.resources.entity_names)   # 应为 {'User'}
print("SDL preview:")
print(app.resources.sdl_generator.generate()[:200])
EOF

uv run python /tmp/test_schema_only.py
```

**预期**：
- `session_factory: None`
- Entities、SDL 正常输出
- 无错误（构造期成功）
- （可选）尝试调 `await app.resources.handler.execute("{ users { id } }")` 应在运行期失败，错误信息表明缺 session_factory

---

## 4. URL 凭据脱敏验证（spec FR-013）

### 4.1 错误消息中的脱敏

```bash
cat > /tmp/test_url_redact.py << 'EOF'
from nexusx.mcp import Application
from sqlmodel import SQLModel

class B(SQLModel): pass
class User(B, table=True):
    id: int

# 故意构造错误的 URL（含密码），让 dispose 或 query 失败
app = Application(
    name="x",
    base=B,
    url="postgresql://user:super_secret_password_123@nonexistent.invalid:5432/db",
)

# 1) __repr__ 不得泄漏密码
print("repr:", repr(app))

# 2) 假设连接失败的错误消息
import asyncio
async def fail():
    try:
        # 触发实际连接（会失败，因为 nonexistent.invalid）
        async with app.session_factory() as session:
            await session.exec(__import__('sqlmodel').select(User))
    except Exception as e:
        msg = str(e)
        if "super_secret_password_123" in msg:
            print("FAIL: password leaked in error:", msg[:200])
        else:
            print("PASS: password redacted. Error preview:", msg[:200])

asyncio.run(fail())
EOF

uv run python /tmp/test_url_redact.py
```

**预期**：
- `repr:` 中 URL 显示为 `postgresql://user:***@nonexistent.invalid:5432/db`
- `PASS: password redacted` —— 错误消息中不含 `super_secret_password_123`

---

## 5. 兼容性验证（spec 用户故事 3）

### 5.1 现有 demo 在 dict 形式下仍工作

```bash
# 临时回退到 dict 形式（如果 PR4 已迁移完，手动改回 dict 测试兼容）
cd demo/multi_app
# 编辑 mcp_server.py 把 Application(...) 换回 {"name": ..., "base": ..., "url": ...}
# 然后：
uv run python -W default::DeprecationWarning -m multi_app.mcp_server 2>&1 | head -20
```

**预期**：进程启动正常 + stderr 出现两条 `DeprecationWarning`（每个 dict app 一条）。

### 5.2 互斥字段报错

```bash
cat > /tmp/test_mutex.py << 'EOF'
from nexusx.mcp import Application
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

class B(SQLModel): pass

# 同时提供 url 与 engine → 应报错
try:
    Application(
        name="x",
        base=B,
        url="sqlite+aiosqlite:///:memory:",
        engine=create_async_engine("sqlite+aiosqlite:///:memory:"),
    )
    print("FAIL: should have raised")
except ValueError as e:
    print("PASS:", e)
EOF

uv run python /tmp/test_mutex.py
```

**预期**：`PASS: Provide at most one of: url, engine, session_factory`

---

## 6. 跨场景回归验证

完成上述全部场景后，跑一次完整测试套件：

```bash
uv run pytest  # 全部测试
uv run ruff check .
uv run mypy src/
```

**预期**：全绿。

---

## 7. 清理

```bash
deactivate 2>/dev/null || true
rm -rf /tmp/test-app-export /tmp/test_app_use.py /tmp/test_schema_only.py /tmp/test_url_redact.py /tmp/test_mutex.py /tmp/test_app_use.db
```

---

## 8. 验证矩阵汇总

| 场景 | 对应 spec 条目 | 验证章节 |
|---|---|---|
| 多 app 合并到 mcp 服务 | 用户故事 1、FR-004、FR-005、SC-001、SC-005 | §2 |
| 独立 app 作为包使用 | 用户故事 2、FR-010、SC-002 | §3 |
| schema-only 模式 | 用户故事 2 验收场景 2、FR-003 | §3.2 |
| URL 凭据脱敏 | FR-013、澄清记录 Q4 | §4 |
| 旧 dict 兼容 | 用户故事 3、FR-009、SC-003 | §5.1 |
| 互斥字段报错 | FR-008 | §5.2 |
| lifespan 自动 dispose | FR-006、FR-007、SC-004 | §2.3 |
| 跨 app 名称冲突 | FR-008 | 由单元测试覆盖（§1） |
| 单元测试全绿 | 所有 FR | §1 |
