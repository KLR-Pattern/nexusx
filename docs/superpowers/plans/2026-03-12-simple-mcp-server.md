# Simple MCP Server Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `create_single_app_mcp_server` function for single-app scenarios with 3 simplified tools.

**Architecture:** Create a new `simple_server.py` module that wraps a single `base` class into an `AppResources` instance and registers 3 tools (`get_schema`, `execute_query`, `execute_mutation`). Reuse existing `AppResources`, `GraphQLHandler`, and error handling infrastructure.

**Tech Stack:** Python, FastMCP, SQLModel, GraphQL

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `src/nexusx/mcp/tools/simple_tools.py` | Create | 3 simplified MCP tools |
| `src/nexusx/mcp/simple_server.py` | Create | `create_single_app_mcp_server` function |
| `src/nexusx/mcp/__init__.py` | Modify | Export `create_single_app_mcp_server` |
| `tests/test_mcp.py` | Modify | Add tests for simple server |

---

## Chunk 1: Simple Tools

### Task 1: Create simple_tools.py with get_schema tool

**Files:**
- Create: `src/nexusx/mcp/tools/simple_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp.py - add to TestMCPServerCreation class

@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
class TestSimpleMCPServer:
    """Tests for simple MCP server."""

    def test_create_simple_mcp_server_returns_sdl(self) -> None:
        """Test that simple server get_schema returns SDL."""
        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.mcp import create_single_app_mcp_server

        class TestBase(SQLModel):
            pass

        class TestUser(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @query
            async def get_all(cls) -> list[TestUser]:
                """Get all users."""
                return []

        mcp = create_single_app_mcp_server(
            base=TestBase,
            name="Test API",
            description="Test description",
        )

        # Get schema via tool
        schema_result = mcp._tool_manager._tools["get_schema"].fn()
        assert "type TestUser" in schema_result
        assert "type Query" in schema_result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp.py::TestSimpleMCPServer::test_create_simple_mcp_server_returns_sdl -v`
Expected: FAIL (module not found or function not defined)

- [ ] **Step 3: Create simple_tools.py with register_simple_tools function**

```python
# src/nexusx/mcp/tools/simple_tools.py
"""Simple MCP tools for single-app scenarios.

This module provides 3 simplified tools without progressive disclosure:
- get_schema: Returns complete GraphQL SDL
- execute_query: Executes GraphQL queries
- execute_mutation: Executes GraphQL mutations
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexusx.mcp.types.errors import (
    MCPErrors,
    create_error_response,
    create_success_response,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from nexusx.mcp.managers.app_resources import AppResources


def register_simple_tools(
    mcp: FastMCP,
    app: AppResources,
    description: str,
) -> None:
    """Register simple MCP tools for single-app scenarios.

    Args:
        mcp: The FastMCP server instance
        app: The AppResources instance for the single application
        description: Description of the GraphQL API
    """

    @mcp.tool()
    def get_schema() -> str:
        """Get the complete GraphQL schema.

        {description}

        Returns the full SDL (Schema Definition Language) including:
        - All Query operations
        - All Mutation operations
        - All type definitions

        Returns:
            Complete GraphQL SDL string.
        """
        return app.sdl_generator.generate()

    @mcp.tool()
    async def execute_query(query: str) -> dict[str, Any]:
        """Execute a GraphQL query.

        Use get_schema() first to understand available queries and types.

        Args:
            query: A GraphQL query string (e.g., "{{ users {{ id name }} }}")

        Returns:
            Dictionary containing:
            - success: True if query succeeded
            - data: The query result (if successful)
            - error: Error message (if failed)
            - error_type: Type of error (if failed)
        """
        if not query or not query.strip():
            return create_error_response(
                "query is required and cannot be empty",
                MCPErrors.MISSING_REQUIRED_FIELD,
            )

        try:
            result = await app.handler.execute(query)

            if "errors" in result:
                error_messages = [
                    err.get("message", "Unknown error") for err in result["errors"]
                ]
                return create_error_response(
                    "; ".join(error_messages),
                    MCPErrors.QUERY_EXECUTION_ERROR,
                )

            return create_success_response(result.get("data"))
        except Exception as e:
            return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)

    @mcp.tool()
    async def execute_mutation(mutation: str) -> dict[str, Any]:
        """Execute a GraphQL mutation.

        Use get_schema() first to understand available mutations and types.

        Args:
            mutation: A GraphQL mutation string

        Returns:
            Dictionary containing:
            - success: True if mutation succeeded
            - data: The mutation result (if successful)
            - error: Error message (if failed)
            - error_type: Type of error (if failed)
        """
        if not mutation or not mutation.strip():
            return create_error_response(
                "mutation is required and cannot be empty",
                MCPErrors.MISSING_REQUIRED_FIELD,
            )

        try:
            result = await app.handler.execute(mutation)

            if "errors" in result:
                error_messages = [
                    err.get("message", "Unknown error") for err in result["errors"]
                ]
                return create_error_response(
                    "; ".join(error_messages),
                    MCPErrors.MUTATION_EXECUTION_ERROR,
                )

            return create_success_response(result.get("data"))
        except Exception as e:
            return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)
```

- [ ] **Step 4: Run test to verify it still fails (function not exported)**

Run: `uv run pytest tests/test_mcp.py::TestSimpleMCPServer::test_create_simple_mcp_server_returns_sdl -v`
Expected: FAIL (ImportError or function not defined)

---

### Task 2: Create simple_server.py

**Files:**
- Create: `src/nexusx/mcp/simple_server.py`

- [ ] **Step 1: Create simple_server.py**

```python
# src/nexusx/mcp/simple_server.py
"""Simple MCP Server for single-app scenarios.

Provides a FastMCP server with 3 simplified tools for lightweight applications.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nexusx.handler import GraphQLHandler
from nexusx.mcp.builders.type_tracer import TypeTracer
from nexusx.mcp.managers.app_resources import AppResources
from nexusx.mcp.tools.simple_tools import register_simple_tools

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def create_single_app_mcp_server(
    base: type,
    name: str = "nexusx API",
    description: str = "GraphQL API for SQLModel entities",
) -> FastMCP:
    """Create a simplified MCP server for single-app scenarios.

    This function creates a FastMCP server with 3 tools optimized for
    single-application use cases:

    - **get_schema**: Returns complete GraphQL SDL
    - **execute_query**: Executes GraphQL queries
    - **execute_mutation**: Executes GraphQL mutations

    Unlike create_multi_app_mcp_server which uses progressive disclosure with 7 tools,
    this simplified version provides direct access to the schema and execution.

    Args:
        base: Base class for SQLModel entities (auto-discovers subclasses
              with @query/@mutation decorators)
        name: Name of the MCP server (shown in MCP clients)
        description: Description of the GraphQL API

    Returns:
        A configured FastMCP server instance.

    Example:
        ```python
        from nexusx.mcp import create_single_app_mcp_server
        from myapp.models import BaseEntity

        mcp = create_single_app_mcp_server(
            base=BaseEntity,
            name="My Blog API",
            description="Blog system with users and posts",
        )

        mcp.run()  # stdio mode (default)
        # mcp.run(transport="streamable-http")  # HTTP mode
        ```
    """
    from mcp.server.fastmcp import FastMCP

    # Create GraphQL handler
    handler = GraphQLHandler(base=base)

    # Create type tracer
    introspection_data = handler._introspection_generator.generate()
    entity_names = {e.__name__ for e in handler.entities}
    tracer = TypeTracer(introspection_data, entity_names)

    # Create AppResources container
    app = AppResources(
        name="app",
        description=description,
        handler=handler,
        tracer=tracer,
        sdl_generator=handler._sdl_generator,
    )

    # Create FastMCP server
    mcp = FastMCP(name)

    # Register simple tools
    register_simple_tools(mcp, app, description)

    return mcp
```

- [ ] **Step 2: Update __init__.py to export create_single_app_mcp_server**

```python
# src/nexusx/mcp/__init__.py
# Update __all__ and add import

__all__ = [
    "create_multi_app_mcp_server",
    "create_single_app_mcp_server",  # Add this
    "AppConfig",
    "MultiAppManager",
    "AppResources",
]

from nexusx.mcp.managers import AppResources, MultiAppManager
from nexusx.mcp.server import create_multi_app_mcp_server
from nexusx.mcp.simple_server import create_single_app_mcp_server  # Add this
from nexusx.mcp.types.app_config import AppConfig
```

- [ ] **Step 3: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py::TestSimpleMCPServer::test_create_simple_mcp_server_returns_sdl -v`
Expected: PASS

---

### Task 3: Add more tests for simple server

**Files:**
- Modify: `tests/test_mcp.py`

- [ ] **Step 1: Add test for execute_query**

```python
# tests/test_mcp.py - add to TestSimpleMCPServer class

    @pytest.mark.asyncio
    async def test_execute_query_returns_data(self) -> None:
        """Test that execute_query returns data."""
        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.mcp import create_single_app_mcp_server

        class TestBase(SQLModel):
            pass

        class TestItem(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @query
            async def get_all(cls) -> list[TestItem]:
                return [TestItem(id=1, name="Test")]

        mcp = create_single_app_mcp_server(base=TestBase, name="Test API")

        # Execute query via tool
        result = await mcp._tool_manager._tools["execute_query"].fn(
            query="{ testItemGetAll { id name } }"
        )

        assert result["success"] is True
        assert "testItemGetAll" in result["data"]
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py::TestSimpleMCPServer::test_execute_query_returns_data -v`
Expected: PASS

- [ ] **Step 3: Add test for execute_query with empty string**

```python
# tests/test_mcp.py - add to TestSimpleMCPServer class

    @pytest.mark.asyncio
    async def test_execute_query_empty_string_returns_error(self) -> None:
        """Test that execute_query with empty string returns error."""
        from sqlmodel import SQLModel

        from nexusx.mcp import create_single_app_mcp_server

        class TestBase(SQLModel):
            pass

        mcp = create_single_app_mcp_server(base=TestBase, name="Test API")

        result = await mcp._tool_manager._tools["execute_query"].fn(query="")

        assert result["success"] is False
        assert "required" in result["error"].lower()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py::TestSimpleMCPServer::test_execute_query_empty_string_returns_error -v`
Expected: PASS

- [ ] **Step 5: Add test for execute_mutation**

```python
# tests/test_mcp.py - add to TestSimpleMCPServer class

    @pytest.mark.asyncio
    async def test_execute_mutation_returns_data(self) -> None:
        """Test that execute_mutation returns data."""
        from sqlmodel import Field, SQLModel

        from nexusx import mutation
        from nexusx.mcp import create_single_app_mcp_server

        class TestBase(SQLModel):
            pass

        class TestProduct(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @mutation
            async def create(cls, name: str) -> TestProduct:
                return TestProduct(id=1, name=name)

        mcp = create_single_app_mcp_server(base=TestBase, name="Test API")

        # Execute mutation via tool
        result = await mcp._tool_manager._tools["execute_mutation"].fn(
            mutation='mutation { testProductCreate(name: "Test") { id name } }'
        )

        assert result["success"] is True
        assert "testProductCreate" in result["data"]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp.py::TestSimpleMCPServer::test_execute_mutation_returns_data -v`
Expected: PASS

- [ ] **Step 7: Run all MCP tests**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: All PASS

- [ ] **Step 8: Commit changes**

```bash
git add src/nexusx/mcp/tools/simple_tools.py
git add src/nexusx/mcp/simple_server.py
git add src/nexusx/mcp/__init__.py
git add tests/test_mcp.py
git commit -m "feat: add create_single_app_mcp_server for single-app scenarios

Add simplified MCP server entry point with 3 tools:
- get_schema: Returns complete GraphQL SDL
- execute_query: Executes GraphQL queries
- execute_mutation: Executes GraphQL mutations

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Summary

| Task | Description | Status |
|------|-------------|--------|
| 1 | Create simple_tools.py with 3 tools | - |
| 2 | Create simple_server.py and update exports | - |
| 3 | Add comprehensive tests | - |

**Final verification:**
- `uv run pytest tests/test_mcp.py -v` - all tests pass
- `uv run ruff check src/nexusx/mcp/` - no lint errors
