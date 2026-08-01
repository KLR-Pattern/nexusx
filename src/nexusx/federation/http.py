"""Injectable httpx transport for RemoteLoader + ER introspection client.

Production uses a lazily-created ``httpx.AsyncClient``. Tests inject a client
backed by ``httpx.ASGITransport`` so member ASGI apps are called in-process
(no real port, no CI flakiness).
"""

from __future__ import annotations

import json
from typing import Any

from nexusx.federation.transport import FederationTransportError


class GraphQLTransport:
    """Default :class:`FederationTransport` — a thin httpx.AsyncClient wrapper.

    This is one implementation of the pluggable transport seam; implement
    :class:`~nexusx.federation.transport.FederationTransport` yourself to plug in
    mTLS, request signing, per-host credentials, etc. Pass a pre-configured
    ``client`` to reuse connection pooling or an ASGI transport (tests), or to
    hand the sidecar/mesh a client tuned to your environment.
    """

    def __init__(self, client: Any | None = None, timeout: float = 30.0) -> None:
        self._client = client
        self._timeout = timeout
        self._owned = client is None

    async def _ensure(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as e:  # pragma: no cover - guarded by extra
                msg = (
                    "nexusx federation requires httpx. Install with "
                    "`pip install nexusx[federation]`."
                )
                raise ImportError(msg) from e
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owned = True
        return self._client

    async def post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json("POST", url, body)

    async def get_json(self, url: str) -> dict[str, Any]:
        return await self._request_json("GET", url)

    async def _request_json(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._ensure()
        try:
            if method == "POST":
                response = await client.post(url, json=body)
            else:
                response = await client.get(url)
        except Exception as exc:
            raise FederationTransportError(method, url, str(exc)) from exc

        if response.status_code >= 400:
            detail = self._response_detail(response)
            raise FederationTransportError(
                method,
                url,
                response.reason_phrase,
                status_code=response.status_code,
                response_detail=detail,
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise FederationTransportError(
                method,
                url,
                "remote response is not valid JSON",
                response_detail=response.text[:1000],
            ) from exc
        if not isinstance(payload, dict):
            raise FederationTransportError(
                method,
                url,
                f"expected a JSON object, got {type(payload).__name__}",
            )
        return dict(payload)

    @staticmethod
    def _response_detail(response: Any) -> str:
        try:
            payload = response.json()
        except Exception:
            return str(response.text)[:1000]
        if isinstance(payload, dict):
            for key in ("detail", "message", "errors"):
                if key in payload:
                    value = payload[key]
                    return value if isinstance(value, str) else json.dumps(value)
        return json.dumps(payload)[:1000]

    async def close(self) -> None:
        if self._owned and self._client is not None:
            await self._client.aclose()
            self._client = None
