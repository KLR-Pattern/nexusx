# Implementation Plan: DTO federation（UseCase 层 / γ 路径 federation）

**Branch**: `016-dto-tree-federation` | **Date**: 2026-08-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/016-dto-tree-federation/spec.md`

## Summary

γ 路径（UseCaseService）的跨服务 federation——member 暴露 public DTO（UseCase 层，subset of 实体 + Resolver 加工，自包含业务树），mounter 的 UseCaseService 关联 member public DTO，Resolver 组合成业务树。β 路径（ER federation）完全不动。

member 侧加三件：SubsetConfig federation 参数（public 标记）+ DTO batch root（跑 er.create_resolver）+ 独立 DTO introspection 端点（暴露 DTOFragment）。mounter 侧：γ 路径 RemoteLoader 取 member public DTO（复用 UseCaseService + Resolver）。

## Technical Context

**Language/Version**: Python ≥3.10
**Primary Dependencies**: SQLModel, SQLAlchemy(async), Pydantic v2, aiodataloader, httpx（nexusx 既有栈，无新增）
**Testing**: pytest（既有 federation e2e ASGITransport + UseCase 模式）
**Project Type**: library
**Constraints**: β 路径完全不动；DTO 不进 ER diagram；member 值只读；零回归（012-014 + 5.0.1）
**Scale/Scope**: ~5 源文件 + 测试。中等偏大。

## Constitution Check

`.specify/memory/constitution.md` 为占位模板（无实际原则）。遵循 nexusx 通用纪律：复用优先、β 不动、向后兼容、fail-fast、N+1-proof。**Gate: PASS**。

## Project Structure

```text
src/nexusx/
├── subset.py                  # ★ SubsetConfig 加 federation_public/federation_join_key
├── loader/registry.py         # ★ ErManager 收集 public DTO
├── federation/
│   ├── contract.py            # ★ DTOFragment(对称 EntityFragment)
│   ├── introspect.py          # ★ 独立 DTO introspection 端点
│   └── remote_loader.py       # ★ RemoteLoader 取 DTO batch root
├── use_case/compose_executor.py # ★ γ 物化 DTO RemoteRef + RemoteLoader 取 DTO 树
└── standard_queries.py        # ★ DTO batch root(跑 er.create_resolver 返 DTO)

tests/
├── test_dto_federation_e2e.py         # 新: γ 组合 member public DTO
├── test_dto_federation_introspect.py  # 新: DTOFragment 收集 + 独立端点
└── test_federation_e2e.py             # 既有: β 回归
```

**Structure Decision**: β 不碰（sdl_generator / SQLModel GraphQL 直查）。member 三件（SubsetConfig / introspect / DTO batch root）+ mounter γ（compose_executor 物化分派 + remote_loader 取 DTO）。

## Complexity Tracking

无 Constitution violation，本节不填。
