# Baseline：修改前的 quickstart 检查 1 命中数

**生成时间**: 2026-07-01
**目的**: 实施完成后跑同一组 grep 对比，验证自洽性

## 检查 1.1 spec 路径统一（grep spec/phase）

```
skill/SKILL.md:247:#### 用户必须输出的明确结论（写入 `spec/phase0.md`）
skill/phases/phase4.md:8:确认后写入 `spec/phase4.md`：
skill/phases/phase3.md:123:进入 Phase 3 编码之前，先与用户确认以下验收项并写入 `spec/phase3.md`：
skill/phases/phase1.md:22:进入 Phase 1 实现之前，在 `spec/phase1.md` 中记录以下验收标准：
skill/phases/phase1.md:59:按验收标准逐条验证，用户确认后才写入 `spec/phase1.md`：
skill/phases/phase2.md:40:进入 Phase 2 编码之前，先与用户确认测试验收集并写入 `spec/phase2.md`：
```

## 检查 1.1 精确版（spec/phaseN）

```
skill/SKILL.md:247:#### 用户必须输出的明确结论（写入 `spec/phase0.md`）
skill/phases/phase4.md:8:确认后写入 `spec/phase4.md`：
skill/phases/phase1.md:22:进入 Phase 1 实现之前，在 `spec/phase1.md` 中记录以下验收标准：
skill/phases/phase1.md:59:按验收标准逐条验证，用户确认后才写入 `spec/phase1.md`：
skill/phases/phase3.md:123:进入 Phase 3 编码之前，先与用户确认以下验收项并写入 `spec/phase3.md`：
skill/phases/phase2.md:40:进入 Phase 2 编码之前，先与用户确认测试验收集并写入 `spec/phase2.md`：
```

## 检查 1.2 argument-hint 残留

```
4:argument-hint: "[项目路径] 创建四阶段项目的目标目录"
```

## 检查 1.3 默认出口声明一致性

### main.py 中默认挂载的出口（除注释外）：
```
17:    GraphQLHandler,
19:    create_use_case_graphql_mcp_server,
21:from nexusx.mcp import create_mcp_server  # noqa: E402
34:graphql_handler = GraphQLHandler(
39:mcp = create_mcp_server(
57:use_case_mcp = create_use_case_graphql_mcp_server(
96:from nexusx import create_use_case_voyager  # noqa: E402
98:voyager_app = create_use_case_voyager(
136:from nexusx import create_use_case_router  # noqa: E402
138:app.include_router(create_use_case_router(use_case_config))
```

## 检查 1.4 router/ 目录

```
FAIL: router/ still exists
total 0
drwxr-xr-x 1 tangkikodo tangkikodo  22 Jul  1 05:45 .
drwxr-xr-x 1 tangkikodo tangkikodo 112 Jul  1 05:45 ..
-rw-r--r-- 1 tangkikodo tangkikodo   0 May 24 22:52 __init__.py
```

## 检查 1.5 service 文件结构对等

=== skill/template/src/service/sprint/ ===
__init__.py
dtos.py
methods.py
service.py
spec.md
test.py
=== skill/template/src/service/task/ ===
__init__.py
dtos.py
methods.py
service.py
spec.md
test.py
=== skill/template/src/service/user/ ===
__init__.py
methods.py
spec.md

## T003 逻辑 tag（git tag 被 hook 拦截）

polish 前 master HEAD SHA：`5b8f06b6413f61d29f324e540d299393b6b0bc7e`

回滚命令（如需）：`git reset --hard 5b8f06b6413f61d29f324e540d299393b6b0bc7e`
