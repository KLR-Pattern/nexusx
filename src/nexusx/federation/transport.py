"""FederationTransport — the pluggable seam for cross-service calls.

nexusx never speaks TLS, auth, or signing itself. Every cross-service call
(federation ER-introspection GET + gql POST) goes through an object implementing
this Protocol. :class:`GraphQLTransport` (in ``http.py``) is the default
httpx-backed implementation; deploy your own to plug in mTLS, request signing,
token refresh, per-host credentials, tracing, retries, etc.

Why a Protocol and not config items (TLSConfig / AuthConfig / ...): naming those
types would mean nexusx *owns* those concepts and must maintain and extend them.
A transport Protocol absorbs nothing — whatever you need lives entirely in your
implementation. And since every method receives the target ``url``, a single
instance can branch per-host (e.g. mTLS for internal services, an API key for an
external one) without nexusx needing any per-service config.

In a service mesh (Istio/Linkerd/...) you usually do nothing: the sidecar
transparently upgrades the default transport's plain ``http://`` calls to mTLS,
so nexusx stays crypto-agnostic without a custom transport at all.

Example — a transport that signs every request::

    import hashlib, hmac, httpx

    class SigningTransport:
        def __init__(self, secret: bytes):
            self._secret = secret
            self._client = httpx.AsyncClient(timeout=30.0)

        def _headers(self, url, body):
            digest = hmac.new(self._secret, (url + str(body)).encode(), hashlib.sha256).hexdigest()
            return {"X-Signature": digest}

        async def post_json(self, url, body):
            r = await self._client.post(url, json=body, headers=self._headers(url, body))
            r.raise_for_status()
            return dict(r.json())

        async def get_json(self, url):
            r = await self._client.get(url, headers=self._headers(url, None))
            r.raise_for_status()
            return dict(r.json())

        async def close(self):
            await self._client.aclose()

    await handler.federate(services={"reviews": "..."}, transport=SigningTransport(secret))
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FederationTransport(Protocol):
    """How federation makes cross-service calls. Implement to plug in security.

    All methods are async. ``post_json`` carries gql query bodies; ``get_json``
    fetches ER introspection. ``close`` is called once on shutdown
    (``GraphQLHandler.aclose()``).
    """

    async def post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST a JSON body (a gql query); return the parsed JSON response."""
        ...

    async def get_json(self, url: str) -> dict[str, Any]:
        """GET a URL (ER introspection); return the parsed JSON response."""
        ...

    async def close(self) -> None:
        """Release resources (connections, clients). Called on shutdown."""
        ...
