"""Tests for ``nexusx.use_case.serialization.serialize_result``.

Locks the JSON-mode behavior so non-JSON-native scalars (UUID, datetime,
Decimal) become strings instead of leaking through as Python objects that
break ``json.dumps`` downstream. Mirrors the pydantic-resolve v5.10.4 fix.
"""

from __future__ import annotations

import datetime
import json
import uuid
from decimal import Decimal

from pydantic import BaseModel

from nexusx.use_case.serialization import serialize_result

# ──────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────

_UUID_VALUE = uuid.UUID("12345678-1234-5678-1234-567812345678")
_DATETIME_VALUE = datetime.datetime(2026, 6, 26, 12, 30, 0)
_DECIMAL_VALUE = Decimal("19.99")


class Inner(BaseModel):
    id: uuid.UUID
    price: Decimal


class Outer(BaseModel):
    inner: Inner
    created_at: datetime.datetime


# ──────────────────────────────────────────────────
# Scalars that previously leaked as Python objects
# ──────────────────────────────────────────────────


class TestScalarSerialization:
    def test_uuid_becomes_string(self):
        assert serialize_result(_UUID_VALUE) == "12345678-1234-5678-1234-567812345678"

    def test_datetime_becomes_string(self):
        result = serialize_result(_DATETIME_VALUE)
        assert result == "2026-06-26T12:30:00"

    def test_decimal_becomes_string_or_float(self):
        # Pydantic JSON mode emits Decimal as float by default; the point is
        # it must be JSON-dumpable, not a Decimal instance.
        result = serialize_result(_DECIMAL_VALUE)
        assert not isinstance(result, Decimal)
        json.dumps(result)  # must not raise


# ──────────────────────────────────────────────────
# BaseModel (the original pydantic-resolve bug)
# ──────────────────────────────────────────────────


class TestBaseModelSerialization:
    def test_basemodel_uuid_field_becomes_string(self):
        result = serialize_result(Inner(id=_UUID_VALUE, price=_DECIMAL_VALUE))
        assert result["id"] == "12345678-1234-5678-1234-567812345678"
        assert not isinstance(result["price"], Decimal)

    def test_nested_basemodel_uuid_fields_become_strings(self):
        result = serialize_result(
            Outer(inner=Inner(id=_UUID_VALUE, price=_DECIMAL_VALUE), created_at=_DATETIME_VALUE)
        )
        assert result["inner"]["id"] == "12345678-1234-5678-1234-567812345678"
        assert result["created_at"] == "2026-06-26T12:30:00"


# ──────────────────────────────────────────────────
# Dict payloads — the case that previously didn't recurse
# ──────────────────────────────────────────────────


class TestDictPayloadSerialization:
    def test_dict_with_uuid_recurses(self):
        payload = {"id": _UUID_VALUE, "name": "alpha"}
        result = serialize_result(payload)
        assert result["id"] == "12345678-1234-5678-1234-567812345678"
        assert result["name"] == "alpha"

    def test_nested_dict_with_uuid_recurses(self):
        payload = {
            "id": _UUID_VALUE,
            "nested": {"item_id": uuid.UUID("87654321-4321-8765-4321-876543218765")},
        }
        result = serialize_result(payload)
        assert result["id"] == "12345678-1234-5678-1234-567812345678"
        assert result["nested"]["item_id"] == "87654321-4321-8765-4321-876543218765"

    def test_dict_with_basemodel_value_recurses(self):
        payload = {"item": Inner(id=_UUID_VALUE, price=_DECIMAL_VALUE)}
        result = serialize_result(payload)
        assert result["item"]["id"] == "12345678-1234-5678-1234-567812345678"

    def test_dict_payload_is_json_dumpable(self):
        # The end-to-end guarantee callers (cli.py, jsonrpc.py) rely on.
        payload = {
            "id": _UUID_VALUE,
            "at": _DATETIME_VALUE,
            "nested": {"item_id": _UUID_VALUE},
        }
        # Must not raise TypeError: Object of type UUID is not JSON serializable
        json.dumps(serialize_result(payload))


# ──────────────────────────────────────────────────
# Lists + passthroughs (regression guard)
# ──────────────────────────────────────────────────


class TestListAndPassthrough:
    def test_list_of_uuids(self):
        result = serialize_result([_UUID_VALUE, _UUID_VALUE])
        assert result == [
            "12345678-1234-5678-1234-567812345678",
            "12345678-1234-5678-1234-567812345678",
        ]

    def test_none(self):
        assert serialize_result(None) is None

    def test_scalars_unchanged(self):
        assert serialize_result("hi") == "hi"
        assert serialize_result(42) == 42
        assert serialize_result(3.14) == 3.14
        assert serialize_result(True) is True
