"""Single-application manager for MCP support."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from nexusx.handler import GraphQLHandler
from nexusx.mcp.builders.type_tracer import TypeTracer

if TYPE_CHECKING:
    from sqlmodel import SQLModel

    from nexusx.standard_queries import AutoQueryConfig


class SingleAppManager:
    """Manages a single GraphQL application without multi-app overhead.

    This class provides a simplified interface for single-app scenarios,
    eliminating the need for app routing and discovery.

    Unlike MultiAppManager, this manager:
    - Does not require app_name routing
    - Provides direct access to handler, tracer, and SDL generator
    - Is designed for single-database scenarios
    """

    def __init__(
        self,
        base: type[SQLModel],
        description: str | None = None,
        session_factory: Callable | None = None,
        enable_pagination: bool = False,
        auto_query_config: AutoQueryConfig | None = None,
    ):
        """Initialize the single-app manager.

        Args:
            base: SQLModel base class. All subclasses with @query/@mutation
                  decorators will be automatically discovered.
            description: Optional description for the GraphQL schema
                        (used for both Query and Mutation type descriptions)
            session_factory: Async session factory for DataLoader relationship loading
            enable_pagination: When True, list relationships return Result types
                with { items, pagination } wrapping.
            auto_query_config: Optional AutoQueryConfig for auto-generating
                standard queries (by_id, by_filter).

        Example:
            ```python
            class BaseEntity(SQLModel):
                pass

            manager = SingleAppManager(
                base=BaseEntity,
                description="Blog system with users and posts"
            )

            # Access handler for query execution
            result = await manager.handler.execute("{ users { id name } }")

            # Get SDL
            sdl = manager.sdl_generator.generate()
            ```
        """
        # Create GraphQL handler for this app
        self.handler = GraphQLHandler(
            base=base,
            session_factory=session_factory,
            query_description=description,
            mutation_description=description,
            enable_pagination=enable_pagination,
            auto_query_config=auto_query_config,
        )

        # Create type tracer for schema introspection
        introspection_data = self.handler.get_introspection_data()
        entity_names = {e.__name__ for e in self.handler.entities}
        self.tracer = TypeTracer(introspection_data, entity_names)

        # Reference to SDL generator
        self.sdl_generator = self.handler.get_sdl_generator()

    @property
    def entity_names(self) -> set[str]:
        """Get the set of entity names in this application.

        Returns:
            Set of entity class names (e.g., {"User", "Post", "Comment"})
        """
        return {e.__name__ for e in self.handler.entities}
