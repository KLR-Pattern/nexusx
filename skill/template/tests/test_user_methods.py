"""UserService / user.methods 测试 — 覆盖正常 + 边界场景。

对应 phase2.md V 降验收表，每个方法至少 1 个正常 + 1 个边界场景。
"""
import pytest

from src.service.user.methods import create_user, list_users


@pytest.mark.asyncio
async def test_create_user_normal(session_factory):
    """正常场景：创建用户返回 User 实体，id 自增、name 与入参一致。"""
    user = await create_user(name="Alice")
    assert user.id is not None
    assert user.name == "Alice"


@pytest.mark.asyncio
async def test_list_users_after_create(session_factory):
    """正常场景：创建多个用户后，list_users 返回全部。"""
    await create_user(name="Alice")
    await create_user(name="Bob")
    users = await list_users()
    assert len(users) == 2
    assert {u.name for u in users} == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_list_users_empty(session_factory):
    """边界场景：空表时返回空列表（非 None、非异常）。"""
    users = await list_users()
    assert users == []
