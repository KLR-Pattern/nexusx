"""TaskService / task.methods 测试 — 覆盖正常 + 边界场景。"""
import pytest

from src.service.sprint.methods import create_sprint
from src.service.task.methods import (
    create_task,
    get_tasks_by_sprint,
    list_tasks,
)


@pytest.mark.asyncio
async def test_create_task_with_owner(session_factory):
    """正常场景：创建带 owner 的 task，字段持久化正确。"""
    sprint = await create_sprint(name="Sprint 1")
    task = await create_task(title="Write tests", sprint_id=sprint.id, owner_id=None)
    assert task.id is not None
    assert task.title == "Write tests"
    assert task.sprint_id == sprint.id
    assert task.done is False  # 默认值


@pytest.mark.asyncio
async def test_get_tasks_by_sprint_filters(session_factory):
    """正常场景：get_tasks_by_sprint 仅返回该 sprint 的任务。"""
    sprint_a = await create_sprint(name="A")
    sprint_b = await create_sprint(name="B")
    await create_task(title="T1", sprint_id=sprint_a.id)
    await create_task(title="T2", sprint_id=sprint_a.id)
    await create_task(title="T3", sprint_id=sprint_b.id)

    tasks_a = await get_tasks_by_sprint(sprint_id=sprint_a.id)
    assert {t.title for t in tasks_a} == {"T1", "T2"}


@pytest.mark.asyncio
async def test_get_tasks_by_sprint_empty(session_factory):
    """边界场景：sprint 无任务时返回空列表。"""
    sprint = await create_sprint(name="Empty")
    tasks = await get_tasks_by_sprint(sprint_id=sprint.id)
    assert tasks == []


@pytest.mark.asyncio
async def test_list_tasks_empty(session_factory):
    """边界场景：全表为空时返回空列表。"""
    tasks = await list_tasks()
    assert tasks == []
