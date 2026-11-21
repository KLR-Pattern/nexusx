"""Mutation confirmation — the contract layer of AI mutation safety.

Drives the SEP-2322 guard pattern through the fastmcp in-memory client:
- leg 1: ``compose_query`` with a mutation returns an ``InputRequiredResult``
  ask (the elicitation handler fires exactly once — the ask is the result of
  the leg, not an error);
- leg 2: the client re-calls with the human's answer —
  accept + true executes the mutation, decline aborts it;
- a client without an elicitation handler (no capability declared) passes
  through ungated — fail-open, demo scope;
- queries are never gated, and parse-broken mutations are not gated either
  (the executor owns surfacing parse errors).
"""

from __future__ import annotations

import json
from typing import Any

from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from pydantic import BaseModel

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_mcp_server import create_use_case_graphql_mcp_server
from nexusx.use_case.types import UseCaseAppConfig


class _ConfItem(BaseModel):
    done: bool


class _ConfService(UseCaseService):
    """Mutation records invocations so tests can prove execution vs abort."""

    calls: list[str] = []

    @query
    async def peek(cls) -> list[str]:
        return list(_ConfService.calls)

    @mutation
    async def do_thing(cls) -> _ConfItem:
        _ConfService.calls.append("do_thing")
        return _ConfItem(done=True)


def _server(*, confirm: bool):
    _ConfService.calls = []
    return create_use_case_graphql_mcp_server(
        apps=[UseCaseAppConfig(name="conf", services=[_ConfService])],
        name="conf-test",
        confirm_mutations=confirm,
    )


_MUTATION = "mutation { _ConfService { do_thing { done } } }"
_QUERY = "query { _ConfService { peek } }"


async def _call_tool(client: Client, query: str) -> dict[str, Any]:
    res = await client.call_tool(
        "compose_query", {"app_name": "conf", "query": query}
    )
    return json.loads(res.content[0].text)


class TestGuardRounds:
    async def test_accept_executes_mutation(self):
        mcp = _server(confirm=True)
        asked: list[str] = []

        async def answer(message, response_type, params, context):
            asked.append(message)
            return True  # auto-wrapped: accept + {"value": true}

        async with Client(mcp, elicitation_handler=answer) as client:
            data = await _call_tool(client, _MUTATION)

        assert asked == [f"Confirm mutation: _ConfService.do_thing. "
                         "Decline to abort without executing."]
        assert data["data"]["_ConfService"]["do_thing"]["done"] is True
        assert _ConfService.calls == ["do_thing"]

    async def test_decline_aborts_mutation(self):
        mcp = _server(confirm=True)

        async def answer(message, response_type, params, context):
            return ElicitResult(action="decline")

        async with Client(mcp, elicitation_handler=answer) as client:
            data = await _call_tool(client, _MUTATION)

        assert data["data"] is None
        assert "declined" in data["errors"][0]["message"]
        assert _ConfService.calls == []  # never executed

    async def test_query_never_gated(self):
        mcp = _server(confirm=True)

        async def fail_if_asked(message, response_type, params, context):
            raise AssertionError("queries must not elicit")

        async with Client(mcp, elicitation_handler=fail_if_asked) as client:
            data = await _call_tool(client, _QUERY)

        assert data["data"]["_ConfService"]["peek"] == []

    async def test_client_without_capability_passes_ungated(self):
        mcp = _server(confirm=True)
        async with Client(mcp) as client:  # no handler → no elicitation capability
            data = await _call_tool(client, _MUTATION)

        assert data["data"]["_ConfService"]["do_thing"]["done"] is True
        assert _ConfService.calls == ["do_thing"]

    async def test_disabled_flag_never_gates(self):
        mcp = _server(confirm=False)

        async def fail_if_asked(message, response_type, params, context):
            raise AssertionError("confirm_mutations=False must not elicit")

        async with Client(mcp, elicitation_handler=fail_if_asked) as client:
            data = await _call_tool(client, _MUTATION)

        assert data["data"]["_ConfService"]["do_thing"]["done"] is True
