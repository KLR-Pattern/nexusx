"""MCP tool annotations — the hint layer of AI mutation safety.

Per the MCP spec, annotations are **untrusted hints**: clients use them for
UI routing and model-side caution (e.g. an agent planning around a
``destructiveHint: true`` tool), never as a security boundary. The contract
layer (server-side gates) is a separate concern.

Rules applied across nexusx MCP servers:

- Discovery/introspection tools are read-only — they cannot change data.
- A tool that executes arbitrary GraphQL (``graphql_query`` /
  ``compose_query``) is only read-only when **no reachable schema exposes a
  Mutation operation**. The ``allow_mutation`` flag gates tool *registration*
  (whether mutation tooling is advertised), not the handler — an execution
  tool pointed at a schema with mutations can still run them, so the
  annotation is computed from schema content, not from the flag.
- Mutation-executing tools carry ``destructiveHint``.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

__all__ = ["destructive", "read_only"]


def read_only() -> ToolAnnotations:
    """Annotations for tools that cannot change data."""
    return ToolAnnotations(read_only_hint=True)


def destructive() -> ToolAnnotations:
    """Annotations for tools that may change or destroy data."""
    return ToolAnnotations(read_only_hint=False, destructive_hint=True)
