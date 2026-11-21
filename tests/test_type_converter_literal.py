"""Unit tests for the shared scalar-Literal helpers in type_converter.

These helpers are the single source of Literal mapping rules for both
GraphQL paths (entity-first SDL/introspection and the compose mapper) —
see nexusx #153. Compose-path behavior is covered end-to-end by
tests/test_compose_literal_types.py; this file pins the shared functions
themselves.
"""

from enum import Enum
from typing import Annotated, Literal, Optional

import pytest
from pydantic import Field

from nexusx.type_converter import (
    describe_literal_values,
    is_literal_annotation,
    literal_allowed_values,
    literal_scalar_type,
)


class TaskStatus(str, Enum):
    OPEN = "open"


class TestIsLiteralAnnotation:
    def test_bare_literal_is_literal(self) -> None:
        assert is_literal_annotation(Literal["open", "closed"]) is True

    def test_wrappers_are_not_literal(self) -> None:
        assert is_literal_annotation(Optional[Literal["open"]]) is False  # noqa: UP045 — typing.Union spelling
        assert is_literal_annotation(list[Literal["open"]]) is False
        assert is_literal_annotation(str) is False


class TestLiteralScalarType:
    def test_string_literal_maps_to_str(self) -> None:
        assert literal_scalar_type(Literal["open", "closed"]) == (str, False)

    def test_int_and_bool_literals(self) -> None:
        assert literal_scalar_type(Literal[1, 2, 3]) == (int, False)
        assert literal_scalar_type(Literal[True, False]) == (bool, False)

    def test_none_member_sets_has_none(self) -> None:
        assert literal_scalar_type(Literal["open", None]) == (str, True)

    def test_optional_wrapper_sets_has_none(self) -> None:
        assert literal_scalar_type(Literal["fast"] | None) == (str, True)
        assert literal_scalar_type(Optional[Literal["fast"]]) == (str, True)  # noqa: UP045 — typing.Union spelling

    def test_annotated_wrapper_is_stripped(self) -> None:
        annotation = Annotated[Literal["fast", "slow"], Field(description="mode")]
        assert literal_scalar_type(annotation) == (str, False)

    def test_non_literal_returns_none(self) -> None:
        assert literal_scalar_type(str) is None
        assert literal_scalar_type(Optional[str]) is None  # noqa: UP045 — typing.Union spelling

    def test_all_none_literal_rejected(self) -> None:
        with pytest.raises(ValueError, match="must contain a non-None value"):
            literal_scalar_type(Literal[None])

    def test_mixed_type_literal_rejected(self) -> None:
        with pytest.raises(ValueError, match="must share one Python type"):
            literal_scalar_type(Literal["open", 1])

    def test_enum_member_literal_rejected_with_hint(self) -> None:
        with pytest.raises(ValueError, match="Use the enum class directly"):
            literal_scalar_type(Literal[TaskStatus.OPEN])

    def test_unsupported_scalar_rejected(self) -> None:
        with pytest.raises(ValueError, match="must use a supported scalar type"):
            literal_scalar_type(Literal[b"bytes"])


class TestLiteralAllowedValues:
    def test_values_unwrapped_through_optional_and_list(self) -> None:
        assert literal_allowed_values(Literal["open", "closed"]) == ("open", "closed")
        assert literal_allowed_values(Optional[Literal["fast"]]) == ("fast",)  # noqa: UP045 — typing.Union spelling
        assert literal_allowed_values(list[Literal["a", "b"]]) == ("a", "b")

    def test_non_literal_returns_none(self) -> None:
        assert literal_allowed_values(str) is None


class TestDescribeLiteralValues:
    def test_appends_allowed_values(self) -> None:
        assert describe_literal_values(None, Literal["open", "closed"]) == (
            "Allowed values: open, closed"
        )

    def test_keeps_existing_description(self) -> None:
        assert describe_literal_values("Run mode.", Literal["fast", "slow"]) == (
            "Run mode. Allowed values: fast, slow"
        )

    def test_booleans_render_as_graphql_literals(self) -> None:
        assert describe_literal_values(None, Literal[True, False]) == (
            "Allowed values: true, false"
        )

    def test_nullable_literal_mentions_null(self) -> None:
        assert describe_literal_values(None, Literal["open", None]) == (
            "Allowed values: open (or null)"
        )
        assert describe_literal_values(None, Literal["fast"] | None) == (
            "Allowed values: fast (or null)"
        )

    def test_non_literal_is_noop(self) -> None:
        assert describe_literal_values("Keep me.", str) == "Keep me."
        assert describe_literal_values(None, int) is None
