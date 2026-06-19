"""Tests for inline literal argument type preservation in GraphQL queries."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from graphql import parse
from sqlmodel import SQLModel, select

from nexusx.decorator import query
from nexusx.execution.argument_builder import ArgumentBuilder
from nexusx.execution.query_executor import QueryExecutor
from nexusx.loader.registry import ErManager
from nexusx.query_parser import QueryParser
from tests.conftest import FixtureUser, get_test_session_factory


class TestArgumentBuilderTypeConversion:
    """Verify that _extract_value preserves Python types from GraphQL literals."""

    def _extract_from_query(self, graphql_query: str, arg_name: str) -> tuple:
        """Parse a GraphQL query and extract argument value via ArgumentBuilder."""
        document = parse(graphql_query)
        # Get the first field's arguments
        for definition in document.definitions:
            for selection in definition.selection_set.selections:
                for arg in selection.arguments:
                    if arg.name.value == arg_name:
                        builder = ArgumentBuilder()
                        return builder._extract_value(arg.value)
        raise ValueError(f"Argument '{arg_name}' not found")

    def test_int_literal_preserved_as_int(self):
        """Inline int literal (e.g. limit: 5) must be int, not str."""
        value = self._extract_from_query("{ users(limit: 5) { id } }", "limit")
        assert value == 5
        assert isinstance(value, int), f"Expected int, got {type(value).__name__}: {value!r}"

    def test_negative_int_literal_preserved(self):
        value = self._extract_from_query("{ users(offset: -1) { id } }", "offset")
        assert value == -1
        assert isinstance(value, int)

    def test_float_literal_preserved_as_float(self):
        value = self._extract_from_query("{ users(ratio: 3.14) { id } }", "ratio")
        assert value == 3.14
        assert isinstance(value, float)

    def test_string_literal_preserved_as_str(self):
        value = self._extract_from_query('{ users(name: "Alice") { id } }', "name")
        assert value == "Alice"
        assert isinstance(value, str)

    def test_boolean_true_preserved(self):
        value = self._extract_from_query("{ users(active: true) { id } }", "active")
        assert value is True

    def test_boolean_false_preserved(self):
        value = self._extract_from_query("{ users(active: false) { id } }", "active")
        assert value is False

    def test_null_literal_preserved(self):
        value = self._extract_from_query("{ users(filter: null) { id } }", "filter")
        assert value is None

    def test_list_of_ints_preserved(self):
        value = self._extract_from_query("{ users(ids: [1, 2, 3]) { id } }", "ids")
        assert value == [1, 2, 3]
        assert all(isinstance(v, int) for v in value)

    def test_nested_object_with_mixed_types(self):
        value = self._extract_from_query(
            '{ users(filter: {age: 25, name: "Bob", active: true}) { id } }',
            "filter",
        )
        assert value == {"age": 25, "name": "Bob", "active": True}
        assert isinstance(value["age"], int)
        assert isinstance(value["active"], bool)


class TestArgumentTypeInE2EQuery:
    """End-to-end test: verify the @query method receives correctly typed arguments."""

    def _build_datetime_args(self, value: str) -> dict:
        """Build arguments for a DateTime literal."""
        class MeetingQuery(SQLModel, table=False):
            async def get_by_time(cls, meeting_time: datetime):
                return None

        document = parse(f'{{ meetingGetByTime(meeting_time: "{value}") {{ id }} }}')
        selection = document.definitions[0].selection_set.selections[0]
        builder = ArgumentBuilder()

        return builder.build_arguments(
            selection,
            None,
            MeetingQuery.get_by_time,
            FixtureUser,
            {"FixtureUser"},
        )

    def test_datetime_literal_with_z_reaches_method_as_utc_datetime(self):
        """A DateTime literal with Z should become UTC aware."""
        args = self._build_datetime_args("2026-05-19T10:30:00Z")

        assert args["meeting_time"] == datetime(2026, 5, 19, 10, 30, tzinfo=timezone.utc)
        assert isinstance(args["meeting_time"], datetime)

    def test_datetime_literal_with_utc_offset_reaches_method_as_utc_datetime(self):
        """A DateTime literal with +00:00 should become UTC aware."""
        args = self._build_datetime_args("2026-05-19T10:30:00+00:00")

        assert args["meeting_time"] == datetime(2026, 5, 19, 10, 30, tzinfo=timezone.utc)

    def test_datetime_literal_with_non_utc_offset_is_normalized_to_utc(self):
        """A DateTime literal with an offset should be normalized to UTC."""
        args = self._build_datetime_args("2026-05-19T18:30:00+08:00")

        assert args["meeting_time"] == datetime(2026, 5, 19, 10, 30, tzinfo=timezone.utc)

    def test_datetime_literal_without_timezone_is_rejected(self):
        """A DateTime literal without timezone information should be rejected."""
        with pytest.raises(ValueError, match="timezone information"):
            self._build_datetime_args("2026-05-19T10:30:00")

    def test_datetime_variable_reaches_method_as_utc_datetime(self):
        """A DateTime variable should be normalized to UTC."""
        class MeetingQuery(SQLModel, table=False):
            async def get_by_time(cls, meeting_time: datetime | None = None):
                return None

        document = parse(
            "query($meeting_time: DateTime) { "
            "meetingGetByTime(meeting_time: $meeting_time) { id } "
            "}"
        )
        selection = document.definitions[0].selection_set.selections[0]
        builder = ArgumentBuilder()

        args = builder.build_arguments(
            selection,
            {"meeting_time": "2026-05-19T18:30:00+08:00"},
            MeetingQuery.get_by_time,
            FixtureUser,
            {"FixtureUser"},
        )

        assert args["meeting_time"] == datetime(2026, 5, 19, 10, 30, tzinfo=timezone.utc)
        assert isinstance(args["meeting_time"], datetime)

    @pytest.mark.usefixtures("test_db")
    async def test_int_argument_reaches_method_as_int(self):
        """A @query method with int param should receive int, not str."""
        received_types: dict[str, type] = {}
        session_factory = get_test_session_factory()

        class UserQuery(SQLModel, table=False):
            @query
            async def get_filtered(cls, limit: int):
                received_types["limit"] = type(limit)
                async with session_factory() as session:
                    result = await session.exec(select(FixtureUser).limit(limit))
                    return list(result.all())

        entities = [FixtureUser]
        registry = ErManager(entities=entities, session_factory=session_factory)
        executor = QueryExecutor(registry)

        method = UserQuery.get_filtered
        query_methods = {"userGetFiltered": (FixtureUser, method)}
        document = parse("{ userGetFiltered(limit: 1) { id name } }")
        parsed = QueryParser().parse_document(document)

        result = await executor.execute_query(
            document,
            None, None, parsed, query_methods, {}, entities,
        )

        assert "data" in result
        assert "userGetFiltered" in result["data"]
        assert received_types.get("limit") is int, (
            f"Expected int, got {received_types.get('limit')}"
        )
