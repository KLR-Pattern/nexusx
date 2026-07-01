"""SprintService / sprint.methods 测试 — 覆盖正常 + 边界场景。"""
import pytest

from src.service.sprint.methods import create_sprint, get_sprint, list_sprints


@pytest.mark.asyncio
async def test_create_sprint_normal(session_factory):
    """正常场景：创建 sprint 返回自增 id。"""
    sprint = await create_sprint(name="Sprint 1")
    assert sprint.id is not None
    assert sprint.name == "Sprint 1"


@pytest.mark.asyncio
async def test_list_sprints_after_create(session_factory):
    """正常场景：多个 sprint 按 id 顺序返回。"""
    await create_sprint(name="Sprint 1")
    await create_sprint(name="Sprint 2")
    sprints = await list_sprints()
    assert len(sprints) == 2
    assert [s.name for s in sprints] == ["Sprint 1", "Sprint 2"]


@pytest.mark.asyncio
async def test_get_sprint_not_found(session_factory):
    """边界场景：查不存在的 id 返回 None（不抛异常）。"""
    sprint = await get_sprint(sprint_id=9999)
    assert sprint is None
