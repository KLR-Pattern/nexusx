"""pytest fixtures — in-memory sqlite + async session factory override.

实现 phase2.md 踩坑 #5：methods.py 的 `from src.db import async_session` 在
导入时绑定原值，运行时仅 patch `src.db.async_session` 不会影响 methods 模块的
局部绑定；必须同时 patch `src.db` 与每个 methods 模块。
"""
import pytest
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession  # SQLModel 扩展版，含 .exec()

import src.db as src_db  # noqa: E402
import src.models  # noqa: F401, E402 — register tables on SQLModel.metadata
import src.service.sprint.methods as sprint_methods
import src.service.task.methods as task_methods
import src.service.user.methods as user_methods


@pytest.fixture
async def session_factory():
    """每测试新建 in-memory sqlite + 干净 schema；yield 一个 session factory。

    自动 patch 生产 session 与各 methods 模块的局部绑定，使 methods.py 在
    测试中走测试 engine。测试结束 dispose engine。
    """
    engine = create_async_engine("sqlite+aiosqlite://", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 同步 patch 4 处：核心 db 模块 + 3 个 service methods 模块
    src_db.async_session = factory
    user_methods.async_session = factory
    task_methods.async_session = factory
    sprint_methods.async_session = factory

    yield factory

    await engine.dispose()
