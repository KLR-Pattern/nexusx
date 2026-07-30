"""Large-scale Voyager demo with 30+ entities.

Run:
    uv run uvicorn demo.enterprise_voyager.voyager_demo:app --port 8010

Open:
    http://localhost:8010/voyager
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from demo.enterprise_voyager.database import ALL_ENTITIES, async_session, init_db
from nexusx import ErManager
from nexusx.voyager import create_use_case_voyager

er = ErManager(entities=ALL_ENTITIES, session_factory=async_session)
voyager_app = create_use_case_voyager(
    services=[],
    er_manager=er,
    name="Enterprise 30+ Entity Demo",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Enterprise Voyager Demo", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/voyager", voyager_app)


@app.get("/")
async def root():
    return {
        "message": "Enterprise Voyager Demo",
        "voyager": "/voyager",
        "entity_count": len(ALL_ENTITIES),
    }
