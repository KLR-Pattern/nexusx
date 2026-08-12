"""Tests for selection.py — parse error paths and runtime type inference."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from nexusx.use_case.selection import (
    SelectionError,
    _infer_runtime_annotation,
    parse_selection,
)


class TestParseSelectionErrors:
    def test_empty_selection_raises(self):
        """Empty string should raise SelectionError."""
        with pytest.raises(SelectionError, match="cannot be empty"):
            parse_selection("")

    def test_whitespace_only_raises(self):
        """Whitespace-only string should raise SelectionError."""
        with pytest.raises(SelectionError, match="cannot be empty"):
            parse_selection("   ")

    def test_selection_with_arguments_raises(self):
        """Selection with arguments should raise SelectionError."""
        # GraphQL parser may reject args or our validation catches them
        with pytest.raises(SelectionError):
            parse_selection("id(name: true)")

    def test_no_fields_raises(self):
        """Selection with no sub-fields should raise SelectionError."""
        # A valid GraphQL query that produces no sub_fields on root
        with pytest.raises(SelectionError):
            parse_selection("")


class TestParseSelectionSuccess:
    def test_bare_field_auto_wrapped(self):
        """A bare field list like 'name' is auto-wrapped and parsed."""
        fs = parse_selection("name")
        assert "name" in fs.sub_fields

    def test_braced_fragment_also_works(self):
        """An already-braced fragment is accepted unchanged."""
        fs = parse_selection("{ name }")
        assert "name" in fs.sub_fields

    def test_nested_bare_selection(self):
        """A bare selection with nested fields is wrapped and parsed."""
        fs = parse_selection("id tasks { title }")
        assert "id" in fs.sub_fields
        assert "tasks" in fs.sub_fields
        assert "title" in fs.sub_fields["tasks"].sub_fields


class TestInferRuntimeAnnotation:
    def test_single_model(self):
        """Single BaseModel instance should return its class."""

        class MyDTO(BaseModel):
            x: int

        result = _infer_runtime_annotation(MyDTO(x=1))
        assert result is MyDTO

    def test_non_model_returns_none(self):
        """Non-BaseModel, non-list should return None."""
        assert _infer_runtime_annotation("string") is None

    def test_non_basemodel_list_returns_none(self):
        """List of non-BaseModel items should return None."""
        assert _infer_runtime_annotation([1, 2, 3]) is None

    def test_mixed_type_list_returns_none(self):
        """List of different BaseModel types should return None."""

        class A(BaseModel):
            a: int

        class B(BaseModel):
            b: int

        assert _infer_runtime_annotation([A(a=1), B(b=2)]) is None

    def test_all_none_list_returns_none(self):
        """List of all None should return None."""
        assert _infer_runtime_annotation([None, None]) is None

    def test_empty_list_returns_none(self):
        """Empty list should return None."""
        assert _infer_runtime_annotation([]) is None

    def test_homogeneous_list(self):
        """List of same BaseModel type should return list[Type]."""

        class MyDTO(BaseModel):
            x: int

        result = _infer_runtime_annotation([MyDTO(x=1), MyDTO(x=2)])
        assert result == list[MyDTO]

    def test_list_with_none_returns_optional_list(self):
        """List with some None items should return list[Type | None]."""

        class MyDTO(BaseModel):
            x: int

        result = _infer_runtime_annotation([MyDTO(x=1), None])
        assert result == list[MyDTO | None]
