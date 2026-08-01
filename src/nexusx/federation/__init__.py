"""nexusx federation — mount other nexusx services into a unified graph.

Relative composition: every nexusx service can mount others — declare
``RemoteRelationship`` (carrying the service url via ``RemoteService``) and run
``await er.initialize()`` at startup; no privileged router role. Data is fetched
by issuing one nested GraphQL query per mounted service (each service resolves
its own composed subgraph with its own executor).

Requires the optional ``nexusx[federation]`` extra (httpx). Calling
``federate()`` without httpx installed raises an informative ImportError.
"""

from nexusx.federation.relationship import (
    RemoteRelationship,
    parse_qualified_name,
)
from nexusx.federation.remote_ref import RemoteRef, RemoteService
from nexusx.federation.transport import (
    FederationTransport,
    FederationTransportError,
)

__all__ = [
    "RemoteRelationship",
    "parse_qualified_name",
    "RemoteRef",
    "RemoteService",
    "FederationTransport",
    "FederationTransportError",
]
