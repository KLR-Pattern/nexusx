"""Tests for QueryParser — GraphQL query parsing and field selection extraction."""

from __future__ import annotations

import pytest

from nexusx.query_parser import FieldSelection, QueryParser


class TestQueryParserBasic:
    def test_parse_simple_query(self):
        """Parser should extract simple scalar field selections."""
        parser = QueryParser()
        result = parser.parse("{ users { id name } }")

        assert "users" in result
        assert "id" in result["users"].sub_fields
        assert "name" in result["users"].sub_fields

    def test_parse_nested_fields(self):
        """Parser should extract nested relationship field selections."""
        parser = QueryParser()
        result = parser.parse("{ users { id posts { title content } } }")

        assert "users" in result
        users = result["users"]
        assert "posts" in users.sub_fields
        posts = users.sub_fields["posts"]
        assert "title" in posts.sub_fields
        assert "content" in posts.sub_fields

    def test_parse_with_nested_arguments(self):
        """Arguments on nested fields should be extracted."""
        parser = QueryParser()
        result = parser.parse("{ users { id posts(limit: 10) { title } } }")

        users = result["users"]
        posts = users.sub_fields["posts"]
        assert posts.arguments == {"limit": 10}

    def test_parse_mutation(self):
        """Parser should parse mutation operations."""
        parser = QueryParser()
        result = parser.parse('mutation { createUser(name: "Alice") { id name } }')

        assert "createUser" in result
        user = result["createUser"]
        assert "id" in user.sub_fields
        assert "name" in user.sub_fields

    def test_parse_multiple_operations(self):
        """Parser should parse multiple field selections in one operation."""
        parser = QueryParser()
        result = parser.parse("{ users { id } posts { title } }")

        assert "users" in result
        assert "posts" in result

    def test_parse_empty_selection(self):
        """Parser should handle operations with no sub-selections on a field."""
        parser = QueryParser()
        # A field with no selection set (scalar root) won't appear in result
        # because parse() only processes fields with selection_set
        result = parser.parse("{ ping }")
        assert result == {}


class TestFieldValueTypes:
    """Test that _value_node_to_python converts all GraphQL value types correctly."""

    def test_int_value(self):
        parser = QueryParser()
        result = parser.parse('{ users { posts(limit: 42) { id } } }')
        assert result["users"].sub_fields["posts"].arguments["limit"] == 42

    def test_float_value(self):
        parser = QueryParser()
        result = parser.parse('{ users { posts(ratio: 3.14) { id } } }')
        assert result["users"].sub_fields["posts"].arguments["ratio"] == pytest.approx(3.14)

    def test_string_value(self):
        parser = QueryParser()
        result = parser.parse('{ users { posts(filter: "hello") { id } } }')
        assert result["users"].sub_fields["posts"].arguments["filter"] == "hello"

    def test_boolean_value(self):
        parser = QueryParser()
        result = parser.parse('{ users { posts(active: true) { id } } }')
        assert result["users"].sub_fields["posts"].arguments["active"] is True

    def test_null_value(self):
        parser = QueryParser()
        result = parser.parse('{ users { posts(ref: null) { id } } }')
        assert result["users"].sub_fields["posts"].arguments["ref"] is None

    def test_list_value(self):
        parser = QueryParser()
        result = parser.parse('{ users { posts(ids: [1, 2, 3]) { id } } }')
        assert result["users"].sub_fields["posts"].arguments["ids"] == [1, 2, 3]

    def test_object_value(self):
        parser = QueryParser()
        q = '{ users { posts(filter: {name: "Alice", age: 30}) { id } } }'
        result = parser.parse(q)
        expected = {"name": "Alice", "age": 30}
        assert result["users"].sub_fields["posts"].arguments["filter"] == expected

    def test_enum_value(self):
        parser = QueryParser()
        result = parser.parse('{ users { posts(sort: ASC) { id } } }')
        assert result["users"].sub_fields["posts"].arguments["sort"] == "ASC"


class TestFieldSelectionDataclass:
    def test_default_values(self):
        sel = FieldSelection()
        assert sel.name == ""
        assert sel.alias is None
        assert sel.arguments == {}
        assert sel.sub_fields == {}

    def test_with_values(self):
        sel = FieldSelection(
            name="users",
            alias="allUsers",
            arguments={"limit": 10},
        )
        assert sel.name == "users"
        assert sel.alias == "allUsers"
        assert sel.arguments == {"limit": 10}


# ──────────────────────────────────────────────────────────────────────
# specs/023 US2: alias key semantics + response-key conflict detection
# ──────────────────────────────────────────────────────────────────────


class TestAliasKeySemantics:
    """sub_fields keys are RESPONSE keys (alias or name); lookups use .name."""

    def test_aliased_fields_are_kept_separately(self):
        """Two aliased invocations of the same field must both survive."""
        parser = QueryParser()
        result = parser.parse(
            '{ S { a: f(x: 1) { id } b: f(x: 2) { id title } } }'
        )
        svc = result["S"]
        # Both response keys survive (6.1.2 kept only the last one).
        assert list(svc.sub_fields) == ["a", "b"]
        # Lookup identity stays the original field name.
        assert svc.sub_fields["a"].name == "f"
        assert svc.sub_fields["b"].name == "f"
        # Arguments stay per-alias.
        assert svc.sub_fields["a"].arguments == {"x": 1}
        assert svc.sub_fields["b"].arguments == {"x": 2}
        # Projections stay per-alias.
        assert list(svc.sub_fields["a"].sub_fields) == ["id"]
        assert list(svc.sub_fields["b"].sub_fields) == ["id", "title"]

    def test_alias_metadata_is_populated(self):
        parser = QueryParser()
        result = parser.parse("{ S { a: f { id } } }")
        sel = result["S"].sub_fields["a"]
        assert sel.alias == "a"
        assert sel.name == "f"

    def test_unaliased_key_unchanged(self):
        """No alias → key stays the field name (backward compatible)."""
        parser = QueryParser()
        result = parser.parse("{ S { f { id } } }")
        assert list(result["S"].sub_fields) == ["f"]
        assert result["S"].sub_fields["f"].alias is None

    def test_mixed_alias_and_plain_coexist(self):
        parser = QueryParser()
        result = parser.parse("{ S { f { id } a: g { id } } }")
        assert set(result["S"].sub_fields) == {"f", "a"}


class TestResponseKeyConflicts:
    """Duplicate response keys at one level raise (no silent dedup, no merging)."""

    def test_duplicate_alias_rejected(self):
        parser = QueryParser()
        with pytest.raises(ValueError, match="conflict"):
            parser.parse("{ S { a: f(x: 1) { id } a: g { id } } }")

    def test_alias_collides_with_field_name_rejected(self):
        parser = QueryParser()
        with pytest.raises(ValueError, match="conflict"):
            parser.parse("{ S { a: f { id } a { id } } }")

    def test_plain_duplicate_field_rejected_no_merging(self):
        """`f { x } f { y }` is legal field-merging per spec — we reject it
        (specs/023 clarify: response keys must be unique; no merging)."""
        parser = QueryParser()
        with pytest.raises(ValueError, match="conflict"):
            parser.parse("{ S { f { x } f { y } } }")

    def test_nested_level_conflict_rejected(self):
        parser = QueryParser()
        with pytest.raises(ValueError, match="conflict"):
            parser.parse("{ S { f { t: id t: name } } }")

    def test_top_level_group_duplicate_rejected(self):
        """`{ A {...} A {...} }` — same family of bug at operation level."""
        parser = QueryParser()
        with pytest.raises(ValueError, match="conflict"):
            parser.parse("{ S { f { id } } S { g { id } } }")

    def test_same_name_in_different_groups_ok(self):
        """Conflicts are per-level: same field name under different parents is fine."""
        parser = QueryParser()
        result = parser.parse("{ A { f { id } } B { f { id } } }")
        assert set(result) == {"A", "B"}


class TestTopLevelAlias:
    """specs/023: entity-group / service level aliases follow the same
    response-key semantics (key = alias, lookup via .name)."""

    def test_top_level_alias_keyed_by_alias(self):
        parser = QueryParser()
        result = parser.parse("{ t: TaskService { list_tasks { id } } }")
        assert list(result) == ["t"]
        assert result["t"].name == "TaskService"
        assert result["t"].alias == "t"
        assert "list_tasks" in result["t"].sub_fields

    def test_two_aliased_groups_coexist(self):
        parser = QueryParser()
        result = parser.parse(
            "{ a: TaskService { list_tasks { id } } "
            "b: TaskService { get_task(task_id: 1) { id } } }"
        )
        assert set(result) == {"a", "b"}
        assert result["a"].name == "TaskService"
        assert result["b"].name == "TaskService"
