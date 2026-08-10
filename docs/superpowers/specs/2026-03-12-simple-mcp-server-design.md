# Simple MCP Server Design

## Overview

Add a simplified MCP server entry point for single-app scenarios, providing only 3 tools instead of the current 7-tool progressive disclosure pattern.

## Motivation

The current `create_multi_app_mcp_server` uses a three-layer progressive disclosure pattern with 7 tools:
- Layer 0: `list_apps`
- Layer 1: `list_queries`, `list_mutations`
- Layer 2: `get_query_schema`, `get_mutation_schema`
- Layer 3: `graphql_query`, `graphql_mutation`

For lightweight single-app applications, this pattern adds unnecessary complexity and MCP description overhead. A simpler entry point with fewer tools is more appropriate.

## Design

### Function Signature

```python
def create_single_app_mcp_server(
    base: type,
    name: str = "nexusx API",
    description: str = "GraphQL API for SQLModel entities",
) -> FastMCP:
    """Create a simplified MCP server for single-app scenarios.

    Args:
        base: Base class for SQLModel entities (auto-discovers subclasses)
        name: Name of the MCP server (shown in MCP clients)
        description: Description of the GraphQL API

    Returns:
        A configured FastMCP server instance with 3 tools:
        - get_schema: Returns complete GraphQL SDL
        - execute_query: Executes GraphQL queries
        - execute_mutation: Executes GraphQL mutations
    """
```

### Usage Example

```python
from nexusx.mcp import create_single_app_mcp_server
from myapp.models import BaseEntity

mcp = create_single_app_mcp_server(
    base=BaseEntity,
    name="My Blog API",
    description="Blog system with users and posts",
)

mcp.run()
```

### Tools Provided

| Tool | Parameters | Return | Description |
|------|------------|--------|-------------|
| `get_schema()` | None | `str` | Returns complete GraphQL SDL |
| `execute_query(query: str)` | GraphQL query string | `dict` | Executes GraphQL query |
| `execute_mutation(mutation: str)` | GraphQL mutation string | `dict` | Executes GraphQL mutation |

### Tool Descriptions

```python
@mcp.tool()
def get_schema() -> str:
    """Get the complete GraphQL schema.

    {description}

    Returns the full SDL (Schema Definition Language) including:
    - All Query operations
    - All Mutation operations
    - All type definitions
    """

@mcp.tool()
async def execute_query(query: str) -> dict:
    """Execute a GraphQL query.

    Use get_schema() first to understand available queries and types.

    Args:
        query: A GraphQL query string (e.g., "{ users { id name } }")
    """

@mcp.tool()
async def execute_mutation(mutation: str) -> dict:
    """Execute a GraphQL mutation.

    Use get_schema() first to understand available mutations and types.

    Args:
        mutation: A GraphQL mutation string
    """
```

## File Structure

```
src/nexusx/mcp/
├── __init__.py              # Export create_single_app_mcp_server
├── server.py                # create_multi_app_mcp_server (existing)
├── simple_server.py         # create_single_app_mcp_server (new)
└── tools/
    ├── multi_app_tools.py   # Existing 7 tools
    └── simple_tools.py      # New 3 tools
```

## Implementation Notes

1. **Reuse existing infrastructure**: Use `AppResources` and related components internally
2. **Single app wrapper**: Internally wrap the single `base` into a single-app config structure
3. **Error handling**: Use existing error types from `types/errors.py`
4. **Response format**: Match the existing success/error response format

## API Export

Update `src/nexusx/mcp/__init__.py`:

```python
__all__ = [
    "create_multi_app_mcp_server",
    "create_single_app_mcp_server",  # New
    "AppConfig",
    "MultiAppManager",
    "AppResources",
]

from nexusx.mcp.server import create_multi_app_mcp_server
from nexusx.mcp.simple_server import create_single_app_mcp_server  # New
```

## Comparison

| Aspect | create_multi_app_mcp_server | create_single_app_mcp_server |
|--------|-------------------|--------------------------|
| Target | Multi-app scenarios | Single-app scenarios |
| Tools | 7 | 3 |
| Schema discovery | Progressive (per operation) | All at once |
| App selection | Required (app_name param) | Not needed |
| Complexity | Higher | Lower |
