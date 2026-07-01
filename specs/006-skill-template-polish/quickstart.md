# Quickstart 验证手册：skill 优化效果确认

**Feature**: 006-skill-template-polish
**用途**: 本 feature 是文档/模板优化，没有运行时端到端流程可验证。本手册定义一组**可执行检查**，用于在本轮改动落地后确认 spec 的 6 条 Success Criteria（SC-001~006）与 4 个用户故事真正达成。

> 实施细节（具体怎么改文件）属于 `tasks.md` 的范围；本文件只定义"如何验证改对了"。

---

## 前置条件

- 工作目录：`/home/tangkikodo/nexusx`
- 本分支已包含本轮所有改动（skill/ 子树修改完成）
- 系统已安装 `uv`、`uvicorn`、`grep`、`pytest`
- 网络：可访问 PyPI（如需走代理，`https_proxy=http://192.168.71.149:16780`）

---

## 检查 1：文档自洽性（对应用户故事 1，FR-001）

**目的**：验证 skill 文档与模板代码无矛盾。

### 1.1 spec 路径统一

```bash
# 期望：除 specs/ 复数形式外，不再有 spec/ 单数路径出现
grep -rn "spec/phase" skill/
# 期望输出：空（或仅匹配到 specs/<编号>-*/ 的子串，无 spec/phase 直接命中）

grep -rn "spec/phase0\|spec/phase1\|spec/phase2\|spec/phase3\|spec/phase4" skill/
# 期望输出：空
```

### 1.2 无非法 frontmatter 字段

```bash
grep -n "argument-hint" skill/SKILL.md
# 期望输出：空
```

### 1.3 模板与 phase3.md 出口声明一致

```bash
# 期望：模板 main.py 默认挂载的出口（除注释外）= phase3.md 推荐默认组合
# REST + UseCase GraphQL MCP + Voyager + GraphQL HTTP
grep -n "create_use_case_router\|create_use_case_graphql_mcp_server\|create_use_case_voyager\|GraphQLHandler" skill/template/src/main.py
# 期望 4 行命中

# 可选出口必须以注释出现
grep -n "create_jsonrpc_router\|create_use_case_cli" skill/template/src/main.py
# 期望命中行均以 # 开头（注释）
```

### 1.4 router 目录已清理

```bash
test ! -d skill/template/src/router/ && echo "PASS: router/ removed" || echo "FAIL"
# 期望：PASS: router/ removed
```

### 1.5 service 文件结构对等

```bash
for d in skill/template/src/service/*/; do
  echo "=== $d ==="
  ls "$d" | grep -v __pycache__ | sort
done
# 期望：三个 service（sprint/task/user）的文件列表对等
# 都包含 __init__.py / methods.py / dtos.py / service.py / spec.md（user 需补齐 dtos.py / service.py）
```

---

## 检查 2：入口总览可读性（对应用户故事 2，FR-002、FR-003、FR-007）

**目的**：验证新用户能在 5 分钟内通过入口总览掌握全貌。

### 2.1 SKILL.md 顶部含入口总览

```bash
# 检查 SKILL.md 前 80 行内是否有"总览/Overview/入口"类章节
head -80 skill/SKILL.md | grep -E "^##.*(总览|Overview|入口|快速参考)"
# 期望：至少 1 行命中
```

### 2.2 Phase 0 已外置

```bash
test -f skill/phases/phase0.md && wc -l skill/phases/phase0.md
# 期望：文件存在，行数 ≥ 100（原 SKILL.md 的 Phase 0 内容约 200 行）

# SKILL.md 不再内联 Phase 0 详细内容
grep -n "Step 0-1\|Step 0-7" skill/SKILL.md
# 期望：空（这些小节已外移到 phases/phase0.md）
```

### 2.3 版本门槛集中声明

```bash
grep -n "nexusx >= 3.2\|适用版本" skill/SKILL.md
# 期望：≥ 1 行命中

# phaseN.md 不再散落版本门槛
grep -rn "3\.0 起\|3\.2+" skill/phases/
# 期望：极少（仅在内联摘要中提及特性版本时出现，无散落门槛声明）
```

---

## 检查 3：模板可运行性（对应 SC-003）

**目的**：验证模板能直接启动，所有端点可访问。

```bash
cd skill/template
uv sync
# 期望：依赖安装成功

# 后台启动
uvicorn src.main:app --port 8765 &
APP_PID=$!
sleep 3

# 探活
curl -sf http://localhost:8765/voyager/ -o /dev/null && echo "PASS voyager" || echo "FAIL voyager"
curl -sf http://localhost:8765/graphql -o /dev/null && echo "PASS graphiql" || echo "FAIL graphiql"
curl -sf http://localhost:8765/openapi.json -o /dev/null && echo "PASS openapi" || echo "FAIL openapi"

# REST 端点示例（具体路径取决于 service）
curl -sf -X POST http://localhost:8765/api/template/sprint_service/list_sprints \
  -H "Content-Type: application/json" -d '{}' && echo "PASS rest" || echo "FAIL rest"

kill $APP_PID
cd ../..
```

**期望**：4 个 PASS 全部命中。

---

## 检查 4：测试位置与可运行性（对应 SC-006、FR-006）

```bash
# 测试文件位置
ls skill/template/tests/
# 期望：test_user_methods.py / test_sprint_methods.py / test_task_methods.py

# service 子目录内无残留 test.py
find skill/template/src/service -name "test.py" -not -path "*/__pycache__/*"
# 期望：空

# 测试运行
cd skill/template
uv run pytest tests/ -v
# 期望：全部通过，至少每个 service 覆盖一个正常场景 + 一个边界场景
cd ../..
```

---

## 检查 5：核心概念自包含（对应 FR-011）

**目的**：验证 phase 文档中外链 docs 已降级为"延伸阅读"，关键概念有 10~20 行内联摘要。

```bash
# phase0.md 含虚拟实体概念摘要（不依赖外部 docs）
grep -n "虚拟实体\|virtual entit" skill/phases/phase0.md
# 期望：命中行附近有 10+ 行解释段落（人工抽查）

# phase3.md 含跨层数据流摘要
grep -n "ExposeAs\|SendTo\|Collector\|跨层数据流" skill/phases/phase3.md
# 期望：命中 + 上下文有摘要段落

# phase3.md 含 3.0 MCP 迁移摘要
grep -n "3.0 UseCase GraphQL MCP\|create_use_case_graphql_mcp_server" skill/phases/phase3.md
# 期望：命中 + 摘要段落
```

---

## 检查 6：spec-management.md 工作流完整性（对应 FR-008、FR-009）

```bash
# 中文化要求已声明
grep -n "中文\|语言要求" skill/spec-management.md
# 期望：≥ 1 行命中

# 迁移指引已写
grep -n "迁移\|migration\|从旧结构" skill/spec-management.md
# 期望：≥ 1 行命中（章节标题）
```

---

## 检查 7：人工评测（对应 SC-001、SC-004）

这两条无法自动化，需要执行下列人工步骤：

### SC-001：新用户首次产出 Phase 1 项目 ≤ 30 分钟

1. 找一名有 FastAPI / SQLModel 基础但未用过 nexusx 的开发者
2. 给他读 `skill/SKILL.md` + `skill/phases/phase0.md` + `skill/phases/phase1.md`
3. 计时：从开始读到产出可运行的 Phase 1 项目（Voyager ER 图可见）
4. 记录耗时，期望 ≤ 30 分钟

### SC-004：phase 文档独立阅读理解度 ≥ 80%

1. 随机抽取 `phases/phase2.md`
2. 让评审者只读该文件（不读其他 phase、不读 SKILL.md）
3. 让他回答 5 个理解度问题：
   - Phase 2 的目标是什么？
   - 需要新增哪些文件？
   - mount_method() 在哪里调用？
   - V 降的验收标准是什么形式？
   - 列出至少 2 个踩坑经验
4. 期望答对 ≥ 4 题（80%）

---

## 通过判定

| 检查项 | 通过条件 |
|---|---|
| 检查 1（自洽性） | 所有 grep 期望命中均为空或符合预期 |
| 检查 2（入口总览） | SKILL.md 含总览章节、Phase 0 外置、版本集中 |
| 检查 3（模板可运行） | 4 个端点 PASS |
| 检查 4（测试位置与运行） | tests/ 下三个文件、pytest 全过 |
| 检查 5（自包含） | 关键概念在 phase 内联，无强制外链 |
| 检查 6（工作流） | 中文化 + 迁移指引均存在 |
| 检查 7（人工评测） | SC-001 ≤ 30 分钟、SC-004 ≥ 80% 理解度 |

任意一项失败 → 返回对应 FR / SC 重新实施，**不允许跳过**。

---

## 验证产物归档

执行完上述检查后，将检查结果（含 grep 输出、curl 输出、pytest 输出、人工评测记录）归档到 `specs/006-skill-template-polish/vv-result.md`（V&V 结果），作为交付前的最终凭证。该文件由实施阶段生成，不在本计划范围内。
