"""Shared serialization + coercion helpers for UseCase surfaces.

These were previously internal to ``server.py`` (the legacy direct-call MCP).
That module is being removed in 3.0 (spec FR-010), but the helpers are still
needed by the orthogonal surfaces that 3.0 keeps: ``jsonrpc.py`` (JSON-RPC
over HTTP) and ``cli.py`` (interactive CLI). They live here so both can share
one implementation without depending on the removed module.
"""

from __future__ import annotations

import inspect
from typing import Any, get_type_hints

from pydantic import BaseModel, TypeAdapter

__all__ = ["coerce_value", "coerce_kwargs", "serialize_result"]


def coerce_value(value: Any, annotation: Any) -> Any:
    """Use Pydantic TypeAdapter to coerce a JSON-native value to the target type.

    Returns the value unchanged if coercion fails (best-effort).
    """
    if value is None:
        return value
    try:
        adapter = TypeAdapter(annotation)
        return adapter.validate_python(value)
    except Exception:  # noqa: BLE001
        return value


def coerce_kwargs(func: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Coerce JSON-parsed kwargs to match ``func``'s parameter type hints.

    Walks ``inspect.signature(func)``, applying ``coerce_value`` to each
    present kwarg. Skips ``cls`` and absent parameters.
    """
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:  # noqa: BLE001
        return kwargs

    sig = inspect.signature(func)
    coerced = dict(kwargs)

    for name, param in sig.parameters.items():
        if name == "cls" or name not in coerced:
            continue
        anno = hints.get(name, param.annotation)
        if anno is inspect.Parameter.empty or anno is None:
            continue
        coerced[name] = coerce_value(coerced[name], anno)

    return coerced


def serialize_result(result: Any) -> Any:
    """Serialize a method result to a JSON-friendly structure.

    All paths use Pydantic JSON mode so non-JSON-native scalars (UUID,
    datetime, Decimal, ...) become strings instead of leaking through as
    Python objects that break ``json.dumps`` downstream. Dicts recurse so
    nested UUIDs / BaseModels inside ``dict`` payloads are also covered.
    Mirrors the pydantic-resolve v5.10.4 fix for compose JSON serialization.
    """
    if result is None:
        return None

    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")

    if isinstance(result, list):
        return [serialize_result(item) for item in result]

    if isinstance(result, dict):
        return {key: serialize_result(value) for key, value in result.items()}

    if isinstance(result, (str, int, float, bool)):
        return result

    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")

    return TypeAdapter(type(result)).dump_python(result, mode="json")
