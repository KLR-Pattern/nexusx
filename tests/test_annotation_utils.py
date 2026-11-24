"""Pins the behaviour of ``nexusx.annotation_utils`` (spec 026 / issue #160 R1).

The expected values were derived by running the *pre-consolidation* private
copies (``TypeConverter``, ``utils.type_utils.is_list_annotation``,
``utils.schema_helpers.get_core_types``, ``use_case.selection._strip_annotated``,
``standard_queries._unwrap_optional_type``) over the same matrix before they
were deleted — so this table is the old behaviour, not an aspiration.
"""

from __future__ import annotations

import typing
from typing import Annotated, Any, Literal, Optional

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Mapped

from nexusx import annotation_utils as au


class X(BaseModel):
    pass


MATRIX: dict[str, Any] = {
    "int": int,
    "str": str,
    "none": type(None),
    "list_int": list[int],
    "list_str_none": list[str] | None,
    "opt_list_x": Optional[list[X]],  # noqa: UP045 — both syntaxes are under test
    "list_opt_x": list[X | None],
    "x_bar_none": X | None,
    "opt_x": Optional[X],  # noqa: UP045
    "ann_x": Annotated[X, "m"],
    "ann_opt_list_x": Annotated[list[X] | None, "p"],
    "mapped_list_x": Mapped[list[X]],
    "mapped_x": Mapped[X],
    "int_str_none": int | str | None,
    "bare_list": list,
    "fwd": "X",
    "lit": Literal["a", "b"],
    "dict_si": dict[str, int],
    "tup": tuple[int, list[X]],
    "union_int_str": typing.Union[int, str],  # noqa: UP007
}


# ──────────────────────────────────────────────────────────
# Optional / Union
# ──────────────────────────────────────────────────────────

IS_OPTIONAL = {
    "list_str_none": True, "opt_list_x": True, "x_bar_none": True, "opt_x": True,
    "int_str_none": True,
}
UNWRAP_OPTIONAL = {  # first non-None arm
    "list_str_none": list[str], "opt_list_x": list[X], "x_bar_none": X, "opt_x": X,
    "int_str_none": int, "union_int_str": int,
}
UNWRAP_OPTIONAL_STRICT = {  # single non-None arm only
    "list_str_none": list[str], "opt_list_x": list[X], "x_bar_none": X, "opt_x": X,
    # int | str | None and Union[int, str] stay unchanged
}


class TestOptional:
    @pytest.mark.parametrize("name", MATRIX)
    def test_is_optional(self, name: str):
        assert au.is_optional(MATRIX[name]) is IS_OPTIONAL.get(name, False)

    @pytest.mark.parametrize("name", MATRIX)
    def test_unwrap_optional(self, name: str):
        anno = MATRIX[name]
        assert au.unwrap_optional(anno) == UNWRAP_OPTIONAL.get(name, anno)

    @pytest.mark.parametrize("name", MATRIX)
    def test_unwrap_optional_strict(self, name: str):
        anno = MATRIX[name]
        assert au.unwrap_optional_strict(anno) == UNWRAP_OPTIONAL_STRICT.get(name, anno)

    def test_strict_keeps_a_real_union(self):
        """The one place the two Optional unwrappers disagree on purpose."""
        assert au.unwrap_optional(int | str | None) is int
        assert au.unwrap_optional_strict(int | str | None) == int | str | None
        assert au.unwrap_optional_strict(typing.Union[int, str]) == typing.Union[int, str]  # noqa: UP007


# ──────────────────────────────────────────────────────────
# list
# ──────────────────────────────────────────────────────────

IS_LIST = {"list_int": True, "list_opt_x": True}
IS_LIST_ANNOTATION = {
    "list_int": True, "list_str_none": True, "opt_list_x": True, "list_opt_x": True,
    "ann_opt_list_x": True, "mapped_list_x": True, "tup": True,
}
LIST_INNER = {
    "list_int": int, "list_str_none": list[str], "opt_list_x": list[X],
    "list_opt_x": X,  # Optional element unwrapped
    "x_bar_none": X, "opt_x": X, "ann_x": X, "ann_opt_list_x": list[X],
    "mapped_list_x": list[X], "mapped_x": X, "int_str_none": int,
    "bare_list": list, "fwd": "X", "lit": "a", "dict_si": str,
    "tup": int, "union_int_str": int,
}


class TestList:
    @pytest.mark.parametrize("name", MATRIX)
    def test_is_list_strict(self, name: str):
        assert au.is_list(MATRIX[name]) is IS_LIST.get(name, False)

    @pytest.mark.parametrize("name", MATRIX)
    def test_is_list_annotation_lenient(self, name: str):
        assert au.is_list_annotation(MATRIX[name]) is IS_LIST_ANNOTATION.get(name, False)

    @pytest.mark.parametrize("name", MATRIX)
    def test_list_inner(self, name: str):
        anno = MATRIX[name]
        assert au.list_inner(anno) == LIST_INNER.get(name, anno)


# ──────────────────────────────────────────────────────────
# Annotated / Mapped
# ──────────────────────────────────────────────────────────

STRIP = {"ann_x": X, "ann_opt_list_x": Optional[list[X]]}  # noqa: UP045
IS_MAPPED = {"mapped_list_x": True, "mapped_x": True}
# Old TypeConverter.unwrap_mapped semantics: ``args[0] if args else anno`` for
# ANY subscripted annotation (not just Mapped) — pinned as-is because callers
# only reach it after ``is_mapped_wrapper`` is True.
UNWRAP_MAPPED = {
    name: (typing.get_args(anno)[0] if typing.get_args(anno) else anno)
    for name, anno in MATRIX.items()
}


class TestAnnotatedAndMapped:
    @pytest.mark.parametrize("name", MATRIX)
    def test_strip_annotated(self, name: str):
        anno = MATRIX[name]
        assert au.strip_annotated(anno) == STRIP.get(name, anno)

    def test_strip_peels_every_layer(self):
        assert au.strip_annotated(Annotated[Annotated[X, 1], 2]) is X

    @pytest.mark.parametrize("name", MATRIX)
    def test_is_mapped_wrapper(self, name: str):
        assert au.is_mapped_wrapper(MATRIX[name]) is IS_MAPPED.get(name, False)

    @pytest.mark.parametrize("name", MATRIX)
    def test_unwrap_mapped(self, name: str):
        anno = MATRIX[name]
        assert au.unwrap_mapped(anno) == UNWRAP_MAPPED.get(name, anno)


# ──────────────────────────────────────────────────────────
# core_types / classes / callables
# ──────────────────────────────────────────────────────────

CORE_TYPES = {
    "int": [int], "str": [str], "none": [], "list_int": [int],
    "list_str_none": [str], "opt_list_x": [X], "list_opt_x": [X],
    "x_bar_none": [X], "opt_x": [X], "ann_x": [X], "ann_opt_list_x": [X],
    "mapped_list_x": [], "mapped_x": [], "int_str_none": [int, str],
    "bare_list": [list], "fwd": [], "lit": [], "dict_si": [], "tup": [],
    "union_int_str": [int, str],
}


class TestCoreTypesAndClasses:
    @pytest.mark.parametrize("name", MATRIX)
    def test_core_types_skips_none_and_non_types(self, name: str):
        assert au.core_types(MATRIX[name]) == CORE_TYPES.get(name, [])

    def test_core_types_handles_sentinels(self):
        assert au.core_types(None) == []
        assert au.core_types(Ellipsis) == []

    def test_is_pydantic_and_safe_issubclass(self):
        assert au.is_pydantic(X) is True
        assert au.is_pydantic(int) is False
        assert au.is_pydantic("X") is False  # type: ignore[arg-type]
        assert au.safe_issubclass(list[int], object) is False  # generic alias is not a class

    def test_unwrap_func(self):
        class Owner:
            @classmethod
            def cm(cls):
                return "cm"

            def bound(self):  # plain method, accessed via the instance below
                return "bound"

        def plain():
            return "plain"

        assert au.unwrap_func(Owner.cm) is Owner.__dict__["cm"].__func__
        assert au.unwrap_func(Owner().bound).__name__ == "bound"
        assert au.unwrap_func(plain) is plain
        assert au.unwrap_func("not-callable") == "not-callable"
