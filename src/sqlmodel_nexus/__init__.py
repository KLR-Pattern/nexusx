"""SQLModel Nexus - GraphQL SDL generation and Core API response building.

This package provides:
- Automatic GraphQL SDL generation from SQLModel classes
- @query/@mutation decorators for defining GraphQL operations
- DataLoader-based relationship resolution
- Per-relationship pagination support
- DefineSubset for creating independent DTO models from SQLModel entities
- ErManager for entity-relationship management and Resolver creation

Example (GraphQL mode):
    ```python
    from sqlmodel import SQLModel, Field, Relationship, select
    from sqlmodel_nexus import query, mutation, GraphQLHandler

    class User(SQLModel, table=True):
        id: int = Field(primary_key=True)
        name: str
        posts: list["Post"] = Relationship(back_populates="author", order_by="id")

        @query
        async def get_users(cls, limit: int = 10) -> list['User']:
            stmt = select(cls).limit(limit)
            result = await session.exec(stmt)
            return list(result.all())

    handler = GraphQLHandler(
        base=User,
        session_factory=async_session,
        enable_pagination=True,
    )
    ```

Example (Core API mode):
    ```python
    from sqlmodel import SQLModel
    from sqlmodel_nexus import DefineSubset, ErManager, Loader

    class UserDTO(DefineSubset):
        __subset__ = (User, ('id', 'name'))

    class PostDTO(DefineSubset):
        __subset__ = (Post, ('id', 'title', 'author_id'))
        author: UserDTO | None = None

        def resolve_author(self, loader=Loader('author')):
            return loader.load(self.author_id)

    er = ErManager(base=SQLModel, session_factory=async_session)
    Resolver = er.create_resolver()
    result = await Resolver().resolve([PostDTO(...) for p in posts])
    ```
"""

from __future__ import annotations

__version__ = "1.9.0"

from sqlmodel_nexus.context import Collector, ExposeAs, SendTo
from sqlmodel_nexus.decorator import mutation, query
from sqlmodel_nexus.er_diagram import ErDiagram
from sqlmodel_nexus.handler import GraphQLHandler
from sqlmodel_nexus.loader import ErManager
from sqlmodel_nexus.query_parser import FieldSelection, QueryParser
from sqlmodel_nexus.relationship import Relationship
from sqlmodel_nexus.resolver import Loader
from sqlmodel_nexus.sdl_generator import SDLGenerator
from sqlmodel_nexus.standard_queries import AutoQueryConfig, add_standard_queries
from sqlmodel_nexus.subset import DefineSubset, SubsetConfig, build_dto_select
from sqlmodel_nexus.use_case import (
    FromContext,
    UseCaseAppConfig,
    UseCaseService,
    create_use_case_mcp_server,
)
from sqlmodel_nexus.use_case import (
    create_router as create_use_case_router,
)
from sqlmodel_nexus.voyager import create_use_case_voyager

__all__ = [
    # Version
    "__version__",
    # Decorators
    "query",
    "mutation",
    # Core classes
    "SDLGenerator",
    "QueryParser",
    "GraphQLHandler",
    "ErManager",
    # Types
    "FieldSelection",
    # Standard queries
    "AutoQueryConfig",
    "add_standard_queries",
    # Core API mode (use case response building)
    "DefineSubset",
    "SubsetConfig",
    "Loader",
    "ExposeAs",
    "SendTo",
    "Collector",
    # Custom relationships
    "Relationship",
    "ErDiagram",
    # Query builder
    "build_dto_select",
    # UseCase MCP mode
    "UseCaseService",
    "UseCaseAppConfig",
    "FromContext",
    "create_use_case_mcp_server",
    "create_use_case_router",
    # Voyager visualization
    "create_use_case_voyager",
]
