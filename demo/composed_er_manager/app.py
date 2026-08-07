"""ComposedErManager demo — two engines composed into one GraphQL schema.

One query traverses blog → shop across engines, **in-process** (no HTTP bridge).
Cf. ``demo/federation`` for the cross-process (HTTP) counterpart; this demo is
its same-process dual (specs/019).

Run::

    uv run uvicorn demo.composed_er_manager.app:app --port 8030

then open http://localhost:8030/graphql and query across engines — ``posts`` is
resolved within the blog engine, ``orders`` hops to the shop engine::

    {
      CmUser {
        get_users {
          name
          posts { title }     # blog engine (same DB)
          orders { total }    # shop engine (cross-engine edge)
        }
      }
    }
"""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from sqlmodel import select

from nexusx import ComposedErManager, ErManager, GraphQLHandler, Relationship

from .database import blog_async_session, init_databases, shop_async_session
from .models import CmOrder, CmOrderItem, CmPost, CmUser


async def orders_by_user(user_ids: list[int]) -> list[list[CmOrder]]:
    """Cross-engine batch loader: blog ``CmUser.id`` → shop ``CmOrder``.

    Runs against the shop session (the target engine); the ComposedErManager
    holds the single loader instance and fans results out per parent.
    """
    async with shop_async_session() as s:
        orders = list(
            (await s.exec(select(CmOrder).where(CmOrder.user_id.in_(user_ids)))).all()
        )
    by_user: dict[int, list[CmOrder]] = {}
    for o in orders:
        by_user.setdefault(o.user_id, []).append(o)
    return [by_user.get(uid, []) for uid in user_ids]


# Two self-contained ErManagers — one engine each, loader wired to its session.
blog_er = ErManager(session_factory=blog_async_session, entities=[CmUser, CmPost])
shop_er = ErManager(session_factory=shop_async_session, entities=[CmOrder, CmOrderItem])

# Compose: delegate-by-entity + the cross-engine edge declared here (DD-02).
composed = ComposedErManager(
    members=[blog_er, shop_er],
    cross_relationships=[
        (
            CmUser,
            Relationship(
                fk="id",
                target=list[CmOrder],
                name="orders",
                loader=orders_by_user,
            ),
        )
    ],
)

# US3 injection path: skip base discovery, delegate resolution to the composed
# registry. @query methods are scanned off `entities=` (MethodScanner), so each
# entry fetches its own session (FR-012: multi-engine standard queries are off).
handler = GraphQLHandler(
    er_manager=composed,
    entities=[CmUser, CmPost, CmOrder, CmOrderItem],
)


class GraphQLRequest(BaseModel):
    query: str
    variables: dict[str, Any] | None = None
    operation_name: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_databases()
    try:
        yield
    finally:
        await handler.aclose()  # delegates to each member (specs/019 review #2)


app = FastAPI(title="nexusx ComposedErManager demo", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/graphql", response_class=HTMLResponse)
async def graphiql_page() -> str:
    return handler.get_graphiql_html(endpoint="/graphql")


@app.post("/graphql")
async def graphql_endpoint(req: GraphQLRequest) -> dict[str, Any]:
    return await handler.execute(req.query, req.variables, req.operation_name)


@app.get("/schema", response_class=PlainTextResponse)
async def schema_endpoint() -> str:
    return handler.get_sdl()


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8030)))
