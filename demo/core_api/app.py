"""Core API Demo — FastAPI application.

Demonstrates nexusx's Core API mode:
- DefineSubset: independent DTOs from SQLModel entities
- Implicit auto-loading: automatic relationship loading with ORM->DTO conversion
- Resolver: model-driven traversal with resolve_/post_ methods
- ExposeAs/SendTo/Collector: cross-layer data flow
- __relationships__: custom non-ORM relationships with hand-written loaders
- ErDiagram: Mermaid ER diagram generation
- build_dto_select: generate column-select statements from DTO definitions

Run:
    uv run uvicorn demo.core_api.app:app --reload

Endpoints:
    GET /api/tasks              — Task list with auto-loaded owner
    GET /api/sprints            — Sprint list with derived fields (post_*)
    GET /api/sprints/{id}/detail — Sprint detail with cross-layer flow
    GET /api/sprints/with-tags  — Sprint list with custom-loaded tags
    GET /api/er-diagram         — Mermaid ER diagram
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from demo.core_api.database import async_session, init_db
from demo.core_api.dtos import (
    SprintDetail,
    SprintSummary,
    SprintTopTasks,
    SprintWithTags,
    TaskSummary,
)
from demo.core_api.models import Sprint, Tag, Task, User
from nexusx import ErDiagram, ErManager, build_dto_select

# ErManager inspects ORM metadata and creates DataLoaders for all
# relationships between the provided entities.
er = ErManager(
    entities=[User, Sprint, Task, Tag],
    session_factory=async_session,
)
Resolver = er.create_resolver()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Core API Demo",
    description="nexusx Core API mode demo",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "message": "Core API Demo",
        "endpoints": {
            "tasks": "/api/tasks — Task list with owner (resolve_* + Loader)",
            "sprints": "/api/sprints — Sprint list with derived fields (post_*)",
            "sprint_detail": "/api/sprints/{id}/detail — Cross-layer data flow",
            "sprints_with_tags": "/api/sprints/with-tags — Custom __relationships__ + AutoLoad",
            "er_diagram": "/api/er-diagram — Mermaid ER diagram",
            "docs": "/docs — FastAPI docs",
        },
    }


@app.get("/api/tasks")
async def get_tasks():
    """Level 2: resolve_* + Loader — load related data via DataLoader.

    build_dto_select generates a select statement with only the columns
    TaskSummary needs. Results are converted to DTOs via dict(row._mapping).
    """
    stmt = build_dto_select(TaskSummary)
    async with async_session() as session:
        rows = (await session.exec(stmt)).all()
    dtos = [TaskSummary(**dict(row._mapping)) for row in rows]
    return await Resolver().resolve(dtos)


@app.get("/api/sprints")
async def get_sprints():
    """Level 3: post_* — derived fields computed after children are resolved.

    SprintSummary.resolve_tasks loads tasks via DataLoader,
    then each TaskSummary.resolve_owner loads owners,
    then post_task_count and post_contributor_names run.
    """
    stmt = build_dto_select(SprintSummary)
    async with async_session() as session:
        rows = (await session.exec(stmt)).all()
    dtos = [SprintSummary(**dict(row._mapping)) for row in rows]
    return await Resolver().resolve(dtos)


@app.get("/api/sprints/{sprint_id}/detail")
async def get_sprint_detail(sprint_id: int):
    """Level 4: ExposeAs + SendTo + Collector — cross-layer data flow.

    - SprintDetail exposes 'sprint_name' to descendants via ExposeAs
    - TaskDetail.post_full_title reads sprint_name from ancestor_context
    - TaskDetail.owner is collected by SprintDetail.post_contributors
    """
    stmt = build_dto_select(SprintDetail, where=Sprint.id == sprint_id)
    async with async_session() as session:
        rows = (await session.exec(stmt)).all()
    if not rows:
        return {"error": "Sprint not found"}
    dto = SprintDetail(**dict(rows[0]._mapping))
    return await Resolver().resolve(dto)


@app.get("/api/er-diagram")
async def get_er_diagram():
    """ErDiagram — generate Mermaid ER diagram from SQLModel metadata.

    Includes both ORM relationships and custom __relationships__.
    """
    diagram = ErDiagram.from_sqlmodel([User, Sprint, Task, Tag])
    return {"mermaid": diagram.to_mermaid()}


@app.get("/api/sprints/with-tags")
async def get_sprints_with_tags():
    """Level 5: Custom __relationships__ + AutoLoad.

    Demonstrates mixing ORM relationships (sprint -> tasks, task -> owner)
    with custom non-ORM relationships (task -> tags via __relationships__).

    - SprintWithTags.tasks: ORM one-to-many (Sprint -> Task)
    - TaskWithTags.owner: ORM many-to-one (Task -> User)
    - TaskWithTags.tags: Custom relationship from __relationships__
      loaded via a hand-written async batch loader
    - post_tag_count: derived field counting custom-loaded tags
    """
    stmt = build_dto_select(SprintWithTags)
    async with async_session() as session:
        rows = (await session.exec(stmt)).all()
    dtos = [SprintWithTags(**dict(row._mapping)) for row in rows]
    return await Resolver().resolve(dtos)


@app.get("/api/sprints/top-tasks")
async def get_sprints_top_tasks(limit: int | None = None, order: str | None = None):
    """Level 6: Paged — top-N tasks per sprint (caller overrides Paged default).

    SprintTopTasks.tasks carries ``Paged(limit=2, order="NEWEST")`` as a
    default; the page_loader slices per-parent (ROW_NUMBER). Query params
    ``?limit=N&order=OLDEST`` flow through Resolver context to override the
    field default per-request — Paged is the params home, context the override.
    """
    stmt = build_dto_select(SprintTopTasks)
    async with async_session() as session:
        rows = (await session.exec(stmt)).all()
    dtos = [SprintTopTasks(**dict(row._mapping)) for row in rows]
    context: dict = {}
    if limit is not None:
        context["limit"] = limit
    if order is not None:
        context["order"] = order
    resolver = Resolver(context=context) if context else Resolver()
    resolved = await resolver.resolve(dtos)
    return [r.model_dump() for r in resolved]


if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
