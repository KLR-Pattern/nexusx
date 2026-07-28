"""nexusx federation — mount other nexusx services into a unified graph.

Relative composition: every nexusx service can mount others via
``er.federate(services={...})``; no privileged router role. Data is fetched by
issuing one nested GraphQL query per mounted service (each service resolves its
own composed subgraph with its own executor).

Requires the optional ``nexusx[federation]`` extra (httpx). Calling
``federate()`` without httpx installed raises an informative ImportError.
"""

from nexusx.federation.relationship import (
    RemoteEdge,
    RemoteRelationship,
    parse_qualified_name,
)
from nexusx.federation.remote_ref import RemoteRef

__all__ = ["RemoteRelationship", "RemoteEdge", "parse_qualified_name", "RemoteRef"]
