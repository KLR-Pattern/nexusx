# Phase 4: OpenAPI → TS SDK

**目标**: 从 FastAPI OpenAPI spec 生成 TypeScript SDK（callable classes + types）。

**前提**: Phase 3 必须使用 `create_use_case_router()` 生成 REST 路由（而非手写 router），才能在 OpenAPI spec 中正确暴露 `response_model`。

**V 降 — 定义验收标准:**
启用 Phase 4 时，将验收标准写入当前需求目录的 `phase4.md`：

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | 每个 DTO 字段都有对应 TS 类型 | 检查 types.gen.ts |
| 2 | 后端字段名（snake_case）原样映射到 TS 类型 | 检查类型字段名 |
| 3 | 嵌套关系在 TS 类型中有正确的递归结构 | 检查嵌套类型定义 |

**实现：**
在项目根目录创建 `fe/` 子目录，使用 `@hey-api/openapi-ts` 生成 SDK：

1. 创建 `fe/openapi-ts.config.ts`：
```typescript
import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: 'http://localhost:8000/openapi.json',
  output: {
    fileName: { suffix: '.gen' },
    path: 'src/sdk',
    header: ['// @ts-nocheck'],
  },
  plugins: [
    '@hey-api/client-fetch',
    '@hey-api/typescript',
    { name: '@hey-api/sdk', operations: { strategy: 'byTags' } },
  ],
});
```

2. 创建 `fe/package.json`，添加依赖和脚本。生成器属于独立工具链，应使用项目实际验证过的精确版本并提交 lockfile；以下版本仅是配置示例：
```json
{
  "scripts": { "generate-client": "openapi-ts" },
  "devDependencies": { "@hey-api/openapi-ts": "0.98.0" }
}
```

3. 安装依赖并生成：
```bash
cd fe && npm install && npm run generate-client
```

**生成产物**:
- `fe/src/sdk/sdk.gen.ts` — 按 tag 分组的 SDK class（如 `WorkspaceService`、`ChatService`）
- `fe/src/sdk/types.gen.ts` — 完整 TS 类型（含嵌套关系）
- `fe/src/sdk/client/` — HTTP client 基础设施

**V 升 — 逐条回查验收:**

- [ ] 1. TS 类型覆盖：所有 UseCaseService 的返回类型都有对应定义
- [ ] 2. 字段名一致：snake_case 字段名与后端一致
- [ ] 3. 嵌套结构：DTO 的关系字段推导为正确的嵌套 TS 类型

## 踩坑经验

1. **不要使用浮动 major/minor 范围生成并提交 SDK** — 固定已验证版本并提交 npm lockfile；升级生成器时重新生成 SDK、检查 diff 并运行 TypeScript 编译
