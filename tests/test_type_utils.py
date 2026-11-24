"""Tests for type_utils module."""


from sqlmodel import Field, SQLModel

from nexusx.utils.type_utils import get_field_type


class EntityForUtilsTest(SQLModel):
    """Test entity for type_utils tests."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    optional_field: str | None = None


class AnotherEntityForUtilsTest(SQLModel):
    """Another test entity."""

    id: int | None
    value: int


class TestGetFieldType:
    """Test cases for get_field_type()."""

    def test_get_field_type_from_model_fields(self) -> None:
        """Test getting field type from model_fields."""
        result = get_field_type(EntityForUtilsTest, "name")
        assert result is str

    def test_get_field_type_optional(self) -> None:
        """Test getting optional field type."""
        result = get_field_type(EntityForUtilsTest, "optional_field")
        # Should return the annotation
        assert result is not None

    def test_get_field_type_non_existent(self) -> None:
        """Test getting type of non-existent field."""
        from typing import Any

        result = get_field_type(EntityForUtilsTest, "non_existent")
        assert result == Any

    def test_get_field_type_primary_key(self) -> None:
        """Test getting type of primary key field."""
        result = get_field_type(EntityForUtilsTest, "id")
        # id is Optional[int] or int | None
        assert result is not None


class TestFkDetectionSingleSource:
    def test_is_fk_field_info_basics(self):
        from types import SimpleNamespace

        from nexusx.utils.type_utils import is_fk_field_info

        assert is_fk_field_info(SimpleNamespace(foreign_key="user.id"))
        assert is_fk_field_info(SimpleNamespace(
            foreign_key=None, metadata=[SimpleNamespace(foreign_key="a.b")]))
        assert not is_fk_field_info(SimpleNamespace(foreign_key=None, metadata=[]))
        assert not is_fk_field_info(SimpleNamespace())

    def test_local_copies_are_gone(self):
        """The verbatim copies no longer exist; the introspector shell (the
        DTO-world variant resolving the source entity) delegates to the
        shared detector."""
        import inspect

        import nexusx.er_diagram as er
        import nexusx.introspection as intro
        import nexusx.sdl_generator as sdl
        import nexusx.subset as subset_mod
        from nexusx.use_case import introspector

        for mod in (er, sdl, intro, subset_mod):
            assert not hasattr(mod, "_is_fk_field"), mod.__name__
        # introspector keeps its shell but its body delegates (no inline FK
        # marker check remains)
        assert "foreign_key" not in inspect.getsource(introspector._is_fk_field)

    def test_get_fk_fields_uses_the_detector(self):
        """Same entity, same verdict through the set API (behavior lock)."""
        from sqlmodel import Field, SQLModel

        from nexusx.utils.type_utils import get_fk_fields, is_fk_field_info

        class E(SQLModel, table=False):
            id: int | None = Field(default=None, primary_key=True)
            owner_id: int = Field(foreign_key="user.id")
            name: str

        assert get_fk_fields(E) == {"owner_id"}
        assert is_fk_field_info(E.model_fields["owner_id"])
        assert not is_fk_field_info(E.model_fields["name"])
