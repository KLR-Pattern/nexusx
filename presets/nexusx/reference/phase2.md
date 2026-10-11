<!-- 同步自 skill/phases/phase2.md；如需更新请同步源文件并在 commit message 中说明 -->

# Phase 2: 方法实现 + Entity 挂载

**目标**: 按业务域实现独立方法，挂载到 Entity 的 @query/@mutation，GraphQL 可查询。

**新增/修改文件**:
- `service/<domain>/methods.py` — 独立业务方法实现（核心逻辑，不含 @query/@mutation 装饰器）
- `models.py` — 新增 `mount_method()` 函数，延迟 import methods 并通过 `_mount()` 挂载到 Entity

**关键模式**:
- 业务方法在 `service/<domain>/methods.py` 中定义，为普通 async 函数（不含 `cls` 参数，非 classmethod）
- `models.py` 通过 `mount_method()` 函数挂载（桥接 classmethod 协议）。函数体内做延迟 import 避免循环依赖，`main.py` 中显式调用：
  ```python
  # models.py 底部
  def mount_method():
      """挂载 service methods 到 entity classes。需在外部显式调用。"""
      import functools
      from nexusx import mutation, query
      from src.service.user.methods import list_users, create_user

      def _mount(entity, fn, decorator):
          @functools.wraps(fn)
          async def wrapper(cls, *args, **kwargs):
              return await fn(*args, **kwargs)
          setattr(entity, fn.__name__, decorator(wrapper))

      _mount(User, list_users, query)
      _mount(User, create_user, mutation)
  ```
  ```python
  # main.py（在 graphql_handler 创建之前调用）
  from src.models import mount_method
  mount_method()
  graphql_handler = GraphQLHandler(base=BaseEntity, session_factory=async_session)
  ```
- `_mount()` 用 `fn.__name__` 作为挂载属性名，`@functools.wraps(fn)` 保留 docstring 确保 GraphQL SDL 正确生成描述
- GraphQL 作为辅助测试接口，`@query`/`@mutation` 装饰器在挂载时应用
- `mount_method()` 定义放在 Entity class 之后、ErManager 之前

**V 降 — 定义验收标准:**
进入 Phase 2 编码之前，先与用户确认测试验收集并写入 `spec/phase2.md`：

| # | 方法 | 测试场景 | 预期结果 | 验证方式 |
|---|------|----------|----------|----------|
| 1 | create_user | 正常创建 | 返回新用户对象，含关联关系 | GraphiQL mutation |
| 2 | create_user | 重复邮箱 | 返回错误提示 | GraphiQL mutation |
| 3 | list_users | 分页查询 | 返回正确分页数据 | GraphiQL query |
| ... | ... | ... | ... | ... |

验收标准要求：
- 每个 `@query`/`@mutation` 至少覆盖：**一个正常场景 + 一个边界/异常场景**
- 异常场景的预期结果必须是可观察的（不写"不出错"，写"返回 status: error, message: xx"）
- 验证方式统一通过 GraphQL query/mutation 在 GraphiQL 中执行

**实现：**
编写 `service/<domain>/methods.py` → `models.py` 挂载

**V 升 — 逐条回查验收:**
启动服务，在 GraphiQL 中逐一执行验收表，同时运行自动化测试：

- [ ] 1. create_user（正常）→ 返回新用户数据，关系字段正确
- [ ] 2. create_user（重复）→ 返回预期错误信息
- [ ] 3. list_users（分页）→ 分页参数生效
- [ ] ...（每条对标验收表）
- [ ] 确认 seed 数据仍可查询，Loader 行为符合预期
- [ ] 自动化测试全部通过：`pytest tests/`

## 踩坑经验

1. **methods.py 函数需通过 `_mount()` 桥接 classmethod 协议** — `query()`/`mutation()` 返回 `classmethod`，会自动注入 `cls` 参数。methods.py 中的独立函数不含 `cls`，直接用 `query(fn)` 挂载到 Entity 后调用会 TypeError。使用 `_mount()` 辅助函数包装一层 `async def wrapper(cls, *args, **kwargs): return await fn(*args, **kwargs)` 来桥接。`@functools.wraps(fn)` 保留 docstring，确保 GraphQL SDL 正确生成描述
2. **`GraphQLHandler` 必须在 `mount_method()` 之后创建** — `GraphQLHandler` 在初始化时扫描 BaseEntity 子类的 `@query`/`@mutation` 方法构建 schema。如果先创建 handler 再挂载方法，GraphQL schema 会为空。`main.py` 中必须先调用 `mount_method()` 再创建 `graphql_handler`
3. **`mount_method()` 定义在 `models.py` 中，`main.py` 显式调用** — 挂载逻辑和 entity 定义放在一起，减少文件跳转。函数体内做延迟 import（`from src.service.xxx.methods import ...`）避免循环依赖。`main.py` 中 `from src.models import mount_method` + `mount_method()` 显式调用，比 import 副作用更清晰
4. **列表关系需要 order_by** — 分页功能要求 `sa_relationship_kwargs={"order_by": "Entity.column"}`
5. **测试需 monkey-patch 每个 methods 模块的 `async_session`** — methods.py 执行 `from src.db import async_session` 时已绑定原始值，运行时 patch `src.db.async_session` 不会影响已导入的局部绑定。必须同时 patch `src.db` 和每个 methods 模块：`monkeypatch.setattr(mod, "async_session", test_factory)`
6. **测试放在项目级 `tests/` 目录** — 不放在 `service/*/` 子目录，避免循环导入（tests 导入 src.models，而 models.py 底部导入 service methods）。每个业务域一个 `test_<domain>_methods.py` 文件
