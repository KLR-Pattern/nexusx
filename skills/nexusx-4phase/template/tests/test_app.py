"""Smoke tests for the generated four-phase application."""

import pytest
from sqlmodel import select
from src.database import init_db
from src.db import async_session
from src.main import app, graphql_handler, use_case_config
from src.models import User


def test_application_surfaces_build() -> None:
    assert app.title == "nexusx Template"
    assert graphql_handler.has_operations
    assert [service.__name__ for service in use_case_config.services] == [
        "UserService",
        "TaskService",
        "SprintService",
    ]


@pytest.mark.asyncio
async def test_database_initializes_with_seed_data() -> None:
    await init_db()

    async with async_session() as session:
        users = list((await session.exec(select(User))).all())

    assert [user.name for user in users] == ["Alice", "Bob", "Charlie"]
