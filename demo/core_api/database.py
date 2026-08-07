"""Database configuration and seed data for the Core API demo."""

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.core_api.models import (
    Comment,
    Label,
    Project,
    Sprint,
    Tag,
    Task,
    TaskLabel,
    User,
)

engine = create_async_engine(f"sqlite+aiosqlite:///{Path(__file__).parent / 'core_api_demo.db'}", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create tables and seed initial data."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with async_session() as session:
        existing = await session.exec(select(User))
        if existing.first():
            return

        # --- Users ---
        users = [
            User(name="Alice"),
            User(name="Bob"),
            User(name="Charlie"),
            User(name="Diana"),
        ]
        for u in users:
            session.add(u)
        await session.commit()
        for u in users:
            await session.refresh(u)

        # --- Projects ---
        projects = [
            Project(name="Platform v2", description="Next generation platform"),
            Project(name="Mobile App", description="Cross-platform mobile application"),
        ]
        for p in projects:
            session.add(p)
        await session.commit()
        for p in projects:
            await session.refresh(p)

        # --- Sprints ---
        sprints = [
            Sprint(name="Sprint 1", project_id=projects[0].id),
            Sprint(name="Sprint 2", project_id=projects[0].id),
            Sprint(name="Sprint 3", project_id=projects[0].id),
            Sprint(name="Sprint 1", project_id=projects[1].id),
        ]
        for s in sprints:
            session.add(s)
        await session.commit()
        for s in sprints:
            await session.refresh(s)

        # --- Tasks ---
        tasks_data = [
            # Project 1, Sprint 1
            ("Setup CI/CD", sprints[0].id, users[0].id, True),
            ("Design database schema", sprints[0].id, users[1].id, True),
            ("Implement auth module", sprints[0].id, users[0].id, False),
            ("Write unit tests", sprints[0].id, users[2].id, False),
            # Project 1, Sprint 2
            ("Build REST API", sprints[1].id, users[1].id, True),
            ("Add pagination support", sprints[1].id, users[0].id, True),
            ("Implement search", sprints[1].id, users[3].id, False),
            ("Code review", sprints[1].id, users[2].id, False),
            # Project 1, Sprint 3
            ("Performance optimization", sprints[2].id, users[0].id, False),
            ("Deploy to production", sprints[2].id, users[3].id, False),
            # Project 2, Sprint 1
            ("Setup React Native", sprints[3].id, users[1].id, True),
            ("Design onboarding flow", sprints[3].id, users[2].id, False),
        ]
        tasks = []
        for title, sprint_id, owner_id, done in tasks_data:
            t = Task(title=title, sprint_id=sprint_id, owner_id=owner_id, done=done)
            session.add(t)
            tasks.append(t)
        await session.commit()
        for t in tasks:
            await session.refresh(t)

        # --- Tags ---
        tags = [
            Tag(name="backend"),
            Tag(name="frontend"),
            Tag(name="devops"),
            Tag(name="testing"),
            Tag(name="urgent"),
        ]
        for t in tags:
            session.add(t)
        await session.commit()

        # --- Labels ---
        labels = [
            Label(name="bug", color="#e74c3c"),
            Label(name="feature", color="#2ecc71"),
            Label(name="improvement", color="#3498db"),
            Label(name="documentation", color="#9b59b6"),
            Label(name="security", color="#e67e22"),
        ]
        for lb in labels:
            session.add(lb)
        await session.commit()
        for lb in labels:
            await session.refresh(lb)

        # --- TaskLabels (many-to-many associations) ---
        task_labels_data = [
            (tasks[0].id, labels[1].id),   # CI/CD -> feature
            (tasks[0].id, labels[4].id),   # CI/CD -> security
            (tasks[1].id, labels[1].id),   # Design schema -> feature
            (tasks[2].id, labels[1].id),   # Auth module -> feature
            (tasks[2].id, labels[4].id),   # Auth module -> security
            (tasks[3].id, labels[3].id),   # Unit tests -> documentation
            (tasks[4].id, labels[1].id),   # REST API -> feature
            (tasks[4].id, labels[2].id),   # REST API -> improvement
            (tasks[6].id, labels[0].id),   # Search -> bug
            (tasks[6].id, labels[2].id),   # Search -> improvement
            (tasks[8].id, labels[2].id),   # Perf optimization -> improvement
            (tasks[9].id, labels[4].id),   # Deploy -> security
            (tasks[10].id, labels[1].id),  # React Native -> feature
            (tasks[11].id, labels[3].id),  # Onboarding -> documentation
        ]
        for task_id, label_id in task_labels_data:
            session.add(TaskLabel(task_id=task_id, label_id=label_id))
        await session.commit()

        # --- Comments ---
        comments_data = [
            (tasks[0].id, users[1].id, "CI pipeline is now live"),
            (tasks[0].id, users[2].id, "Great work on the GitHub Actions setup"),
            (tasks[1].id, users[0].id, "Schema looks good, approved"),
            (tasks[2].id, users[3].id, "Should we add OAuth2 support?"),
            (tasks[4].id, users[0].id, "API docs are auto-generated now"),
            (tasks[4].id, users[2].id, "Need to add rate limiting"),
            (tasks[6].id, users[1].id, "Elasticsearch integration is ready"),
            (tasks[8].id, users[3].id, "Query performance improved by 3x"),
            (tasks[10].id, users[0].id, "Expo setup works great on iOS"),
        ]
        for task_id, author_id, content in comments_data:
            session.add(Comment(content=content, task_id=task_id, author_id=author_id))
        await session.commit()
