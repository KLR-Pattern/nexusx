"""GraphQL execution handler for SQLModel entities."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from graphql import parse

from nexusx.discovery import EntityDiscovery
from nexusx.execution.query_executor import QueryExecutor
from nexusx.graphiql import GRAPHIQL_HTML
from nexusx.introspection import IntrospectionGenerator
from nexusx.loader.registry import ErManager
from nexusx.query_parser import QueryParser, ResponseKeyConflictError
from nexusx.sdl_generator import SDLGenerator
from nexusx.standard_queries import AutoQueryConfig, add_standard_queries

if TYPE_CHECKING:
    # specs/019: er_manager 注入路径接受任意 LoaderRegistry（ErManager / ComposedErManager）
    from nexusx.loader.registry import LoaderRegistry

logger = logging.getLogger(__name__)


class _LiveIntrospection:
    """Adapter so the executor's ``__schema``/``__type`` dispatch always reads the
    handler's current (version-cached) introspection generator. Reflects a
    federated ER graph after ``er.initialize()`` without re-pointing the executor.
    """

    def __init__(self, handler: GraphQLHandler) -> None:
        self._handler = handler

    def execute_field(self, selection: Any, variables: Any) -> Any:
        return self._handler._introspection_generator.execute_field(selection, variables)


class GraphQLHandler:
    """Handles GraphQL query execution for SQLModel entities.

    Uses DataLoader for relationship resolution instead of SQLAlchemy eager loading.

    Example:
        ```python
        handler = GraphQLHandler(
            base=BaseEntity,
            session_factory=async_session,
            enable_pagination=True,
        )
        result = await handler.execute('{ users { id name posts { items { title } } } }')
        ```
    """

    def __init__(
        self,
        base: type | None = None,
        session_factory: Callable | None = None,
        query_description: str | None = None,
        mutation_description: str | None = None,
        auto_query_config: AutoQueryConfig | None = None,
        enable_pagination: bool = False,
        service_name: str | None = None,
        expose_mounted_endpoints: bool = False,
        dto_classes: list[type] | None = None,
        er_manager: LoaderRegistry | None = None,
        entities: list[type] | None = None,
    ):
        """Initialize the GraphQL handler.

        Two mutually-exclusive construction paths:

        - ``base=`` (default): discover entities from a SQLModel base, build an
          ErManager internally.
        - ``er_manager=`` (specs/019 US3, injection): inject a pre-built
          ``LoaderRegistry`` (e.g. ComposedErManager for multi-engine) + an
          explicit ``entities`` list. Skips discovery and internal ErManager
          construction; relationship resolution delegates to the injected
          registry (``QueryExecutor`` calls ``er_manager.create_resolver()``).
          ``auto_query_config`` is unsupported here — multi-engine standard
          queries have ambiguous session ownership (FR-012), use ``@query``
          methods that fetch their own session.

        Args:
            base: SQLModel base class. All subclasses with @query/@mutation
                  decorators will be automatically discovered.
            session_factory: Async session factory for DataLoader queries.
                Required when entities have relationships.
                If auto_query_config is provided, its session_factory is used as fallback.
            query_description: Optional custom description for Query type.
            mutation_description: Optional custom description for Mutation type.
            auto_query_config: Optional AutoQueryConfig for auto-generating
                               standard queries (by_id, by_filter).
            enable_pagination: When True, list relationships return Result types
                with { items, pagination } wrapping.
            service_name: This service's own name (prefix); required for a
                federable member (its ER-introspection payload carries it).
            expose_mounted_endpoints: When True, this member advertises the
                endpoints of services it itself mounts (enables transitive
                discovery by services that mount THIS one). Defaults to False —
                internal URLs are suppressed from the introspection payload
                (they leak network topology); mounters must resolve transitive
                services from their own ``services=`` map instead.
            dto_classes: Optional list of DefineSubset DTO classes this member
                owns. Those flagged federation_public (via SubsetConfig) are
                exposed through the DTO introspection endpoint for γ-path
                federation (specs/016). Default None — no public DTOs.
            er_manager: Pre-built ``LoaderRegistry`` (e.g. ComposedErManager).
                Mutually exclusive with ``base`` (specs/019 US3).
            entities: Entity classes to expose on the injection path. Defaults
                to ``er_manager.get_all_entities()``.
        """
        if er_manager is not None and base is not None:
            raise ValueError("Provide at most one of: base, er_manager")
        if er_manager is None and base is None:
            raise ValueError("GraphQLHandler requires either base= or er_manager=")

        if auto_query_config is not None and session_factory is None:
            raise ValueError(
                "auto_query_config requires a session_factory (a database "
                "connection). Pass session_factory to GraphQLHandler, "
                "Application (url/engine/session_factory), or the MCP builder."
            )

        self.session_factory = session_factory
        self.enable_pagination = enable_pagination
        self._query_description = query_description
        self._mutation_description = mutation_description

        if er_manager is not None:
            # specs/019 US3 注入路径：用预构造 registry + 合并实体集，跳过 discovery
            # 与内部 ErManager 构造。关系解析委托注入的 registry（multi-engine）。
            if auto_query_config is not None:
                raise ValueError(
                    "auto_query_config is not supported with er_manager injection "
                    "(multi-engine standard queries have ambiguous session ownership; "
                    "use @query methods that fetch their own session)"
                )
            self._er_manager = er_manager
            self.entities = (
                list(entities) if entities is not None
                else er_manager.get_all_entities()
            )
        else:
            # Discover entities with decorators and their related entities
            discovery = EntityDiscovery(base)
            self.entities = discovery.discover(include_all=auto_query_config is not None)

            # Add standard queries if auto_query_config is provided. The config is
            # pure policy; the session_factory comes from this handler (resolved
            # from the caller — Application / builder / direct).
            if auto_query_config is not None:
                add_standard_queries(self.entities, auto_query_config, session_factory)

            # Build ErManager for DataLoader-based relationship resolution
            self._er_manager = ErManager(
                entities=self.entities,
                session_factory=session_factory,
                enable_pagination=enable_pagination,
                service_name=service_name,
                expose_mounted_endpoints=expose_mounted_endpoints,
                dto_classes=dto_classes,
            )

            # specs/016 γ-path: register a DTO batch root per federation-public DTO
            # the member owns (served by /nexusx/dto-batch). No-op for β-only
            # members; runs after ErManager is built so the batch root's
            # create_resolver() sees the wired entity set at query time.
            from nexusx.standard_queries import add_dto_batch_roots

            add_dto_batch_roots(self._er_manager)

        # SDL / introspection generators are built LAZILY off the live ErManager,
        # version-cached: they refresh automatically after er.initialize() adds
        # materialized remote types, with no handler-side rebuild.
        self._sdl_cache: tuple[int, SDLGenerator] | None = None
        self._intro_cache: tuple[int, IntrospectionGenerator] | None = None

        # Parse queries for field selection
        self._query_parser = QueryParser()

        # Scan for @query and @mutation methods
        from nexusx.scanning import MethodScanner

        self._scanner = MethodScanner()
        self._query_methods, self._mutation_methods = self._scanner.scan(self.entities)

        # Initialize executor with DataLoader support. The introspection adapter
        # reads the live (version-cached) generator, so __schema reflects federation.
        self._executor = QueryExecutor(
            loader_registry=self._er_manager,
            enable_pagination=enable_pagination,
            introspection_generator=_LiveIntrospection(self),
        )

    @property
    def has_operations(self) -> bool:
        """Whether any @query/@mutation methods were discovered.

        Includes auto-generated by_id/by_filter from auto_query_config.
        Used by MCP server builders to fail fast when a schema would have
        no operations (no @query/@mutation and no auto_query_config).
        """
        return bool(self._query_methods) or bool(self._mutation_methods)

    @property
    def _sdl_generator(self) -> SDLGenerator:
        """Version-cached SDLGenerator over the live ER graph (all entities).

        Lazy: rebuilds only when ``er._version`` changes (e.g. after
        ``er.initialize()``), so the SDL reflects materialized remote types with
        no handler-side rebuild step. Kept under the old name for compatibility.
        """
        v = self._er_manager.version
        if self._sdl_cache is None or self._sdl_cache[0] != v:
            self._sdl_cache = (
                v,
                SDLGenerator(
                    self._er_manager.get_all_entities(),
                    query_description=self._query_description,
                    mutation_description=self._mutation_description,
                ),
            )
        return self._sdl_cache[1]

    @property
    def _introspection_generator(self) -> IntrospectionGenerator:
        """Version-cached IntrospectionGenerator over the live ER graph."""
        v = self._er_manager.version
        if self._intro_cache is None or self._intro_cache[0] != v:
            self._intro_cache = (
                v,
                IntrospectionGenerator(
                    entities=self._er_manager.get_all_entities(),
                    query_methods=self._query_methods,
                    mutation_methods=self._mutation_methods,
                    query_description=self._query_description,
                    mutation_description=self._mutation_description,
                    enable_pagination=self.enable_pagination,
                    loader_registry=self._er_manager,
                ),
            )
        return self._intro_cache[1]

    @property
    def er(self) -> LoaderRegistry:
        """The ER-diagram registry — owns entities, relationships, and (for
        ErManager) federation. ``await handler.er.initialize()`` runs federation
        on the base path. On the er_manager injection path (specs/019) this
        returns the injected registry (e.g. ComposedErManager); its management
        methods (federate/initialize) are unavailable — those run on sub-members."""
        return self._er_manager

    def get_sdl(self, include_mutations: bool = True) -> str:
        """Get the GraphQL Schema Definition Language string.

        Args:
            include_mutations: If True (default), include the Mutation type.
                Set False for read-only schemas.

        Returns:
            SDL string representing the GraphQL schema.
        """
        return self._sdl_generator.generate(
            include_mutations=include_mutations,
            enable_pagination=self.enable_pagination,
            loader_registry=self._er_manager,
        )

    def get_sdl_generator(self) -> SDLGenerator:
        """Get the public SDL generator used by this handler."""
        return self._sdl_generator

    def get_introspection_data(self) -> dict[str, Any]:
        """Get GraphQL introspection data for the current schema."""
        return self._introspection_generator.generate()

    def get_graphiql_html(self, endpoint: str = "/graphql") -> str:
        """Get the GraphiQL HTML template.

        Args:
            endpoint: GraphQL API endpoint URL. Defaults to "/graphql".

        Returns:
            HTML string for GraphiQL playground.
        """
        return GRAPHIQL_HTML.replace("{graphql_url}", endpoint)

    async def aclose(self) -> None:
        """Close federation resources (httpx.AsyncClient). Call on shutdown.

        specs/019 注入路径下 ``er_manager`` 是 ComposedErManager（按 FR-013 无
        ``aclose_federation``），federation 资源在各子 member —— 逐个委托。
        """
        members = getattr(self._er_manager, "_members", None)
        if members is not None:
            for m in members:
                closer = getattr(m, "aclose_federation", None)
                if closer is not None:
                    await closer()
        else:
            closer = getattr(self._er_manager, "aclose_federation", None)
            if closer is not None:
                await closer()

    async def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query.

        Args:
            query: GraphQL query string.
            variables: Optional variables for the query.
            operation_name: Optional operation name for multi-operation documents.

        Returns:
            Dictionary with 'data' and/or 'errors' keys.
        """
        try:
            # Parse once; share the AST between parser and executor.
            # (specs/023: aliases are supported at method level — the old
            # blanket `validate_no_aliases` guard is retired from this call
            # path; the parser now rejects duplicate response keys instead.)
            document = parse(query)
            parsed_selections = self._query_parser.parse_document(
                document, variables=variables
            )

            # Execute via DataLoader-based executor
            return await self._executor.execute_query(
                document=document,
                variables=variables,
                operation_name=operation_name,
                parsed_selections=parsed_selections,
                query_methods=self._query_methods,
                mutation_methods=self._mutation_methods,
                entities=self.entities,
            )

        except ResponseKeyConflictError as e:
            # specs/023 FR-007: carry the machine-readable code on the
            # entity-first path too (aligned with compose's ALIAS_CONFLICT).
            return {
                "errors": [
                    {
                        "message": str(e),
                        "extensions": {"code": "ALIAS_CONFLICT"},
                    }
                ]
            }
        except Exception as e:
            logger.exception("GraphQL execution error")
            return {"errors": [{"message": str(e)}]}
