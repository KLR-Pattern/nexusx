"""Injectable httpx transport for RemoteLoader + ER introspection client.

Production uses a lazily-created ``httpx.AsyncClient``. Tests inject a client
backed by ``httpx.ASGITransport`` so member ASGI apps are called in-process
(no real port, no CI flakiness).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class GraphQLTransport:
    """Thin async JSON-over-HTTP wrapper around an ``httpx.AsyncClient``."""

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
        client = await self._ensure()
        r = await client.post(url, json=body)
        r.raise_for_status()
        return dict(r.json())

    async def get_json(self, url: str) -> dict[str, Any]:
        client = await self._ensure()
        r = await client.get(url)
        r.raise_for_status()
        return dict(r.json())

    async def close(self) -> None:
        if self._owned and self._client is not None:
            await self._client.aclose()
            self._client = None
