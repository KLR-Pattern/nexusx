"""Tests for paginated loaders and pagination utilities."""

from __future__ import annotations

import pytest

from nexusx.loader.factories import (
    _apply_filters,
    _apply_load_only,
    _build_page_result,
    create_page_many_to_many_loader,
    create_page_one_to_many_loader,
)
from nexusx.loader.pagination import (
    PageArgs,
    PageLoadCommand,
    Pagination,
    _build_pagination_model,
    create_result_type,
)
from tests.conftest import get_test_session_factory

# ---------------------------------------------------------------------------
# pagination.py: PageArgs
# ---------------------------------------------------------------------------


class TestPageArgs:
    def test_effective_limit_with_limit(self):
        pa = PageArgs(limit=5, max_page_size=100)
        assert pa.effective_limit == 5

    def test_effective_limit_exceeds_max(self):
        pa = PageArgs(limit=200, max_page_size=100)
        assert pa.effective_limit == 100

    def test_effective_limit_none_returns_default(self):
        pa = PageArgs(limit=None, default_page_size=15)
        assert pa.effective_limit == 15

    def test_invalid_default_page_size(self):
        with pytest.raises(ValueError, match="default_page_size"):
            PageArgs(default_page_size=0)

    def test_invalid_max_page_size(self):
        with pytest.raises(ValueError, match="max_page_size"):
            PageArgs(max_page_size=0)

    def test_invalid_negative_limit(self):
        with pytest.raises(ValueError, match="limit"):
            PageArgs(limit=-1)

    def test_invalid_negative_offset(self):
        with pytest.raises(ValueError, match="offset"):
            PageArgs(offset=-1)


# ---------------------------------------------------------------------------
# pagination.py: _build_pagination_model & create_result_type
# ---------------------------------------------------------------------------


class TestBuildPaginationModel:
    def test_empty_selection_returns_base(self):
        model = _build_pagination_model(set())
        assert model is Pagination

    def test_has_more_only(self):
        model = _build_pagination_model({"has_more"})
        assert "has_more" in model.model_fields
        assert "total_count" not in model.model_fields

    def test_both_fields(self):
        model = _build_pagination_model({"has_more", "total_count"})
        assert "has_more" in model.model_fields
        assert "total_count" in model.model_fields


class TestCreateResultType:
    def test_without_pagination(self):
        Result = create_result_type(int)
        assert "items" in Result.model_fields
        assert "pagination" not in Result.model_fields

    def test_with_pagination(self):
        Result = create_result_type(int, pagination_selection={"has_more"})
        assert "items" in Result.model_fields
        assert "pagination" in Result.model_fields

    def test_from_attributes_config_detected_for_sqlmodel(self):
        from sqlmodel import SQLModel

        class SimpleModel(SQLModel, table=False):
            x: int

        # Verify SQLModel sets from_attributes — the config that create_result_type checks
        assert SimpleModel.model_config.get("from_attributes") is True
        # create_result_type reads this and passes {"from_attributes": True} to create_model
        # Full create_model call can't be tested with list[SQLModel] due to pydantic limitation

    def test_no_from_attributes(self):
        Result = create_result_type(int)
        assert "from_attributes" not in Result.model_config


# ---------------------------------------------------------------------------
# factories.py: _build_page_result
# ---------------------------------------------------------------------------


class TestBuildPageResult:
    def test_entity_passthrough(self):
        class FakeEntity:
            model_fields = {"name": ...}

        obj = FakeEntity()
        obj.name = "test"
        result = _build_page_result(
            rows=[obj],
            page_args=PageArgs(limit=10),
            total_count=1,
            has_next_page=False,
        )
        assert result["items"] == [obj]

    def test_dict_conversion(self):
        from pydantic import BaseModel as PydanticBase

        class FakeEntity(PydanticBase):
            name: str
            id: int

            class Config:
                model_fields = {"name": ..., "id": ...}

        result = _build_page_result(
            rows=[{"name": "test", "id": 1, "extra": "ignored"}],
            page_args=PageArgs(limit=10),
            total_count=1,
            has_next_page=False,
            entity_kls=FakeEntity,
        )
        assert len(result["items"]) == 1
        assert result["items"][0].name == "test"

    def test_truncates_by_effective_limit(self):
        result = _build_page_result(
            rows=[1, 2, 3, 4, 5],
            page_args=PageArgs(limit=2),
            total_count=5,
            has_next_page=True,
        )
        assert result["items"] == [1, 2]
        assert result["pagination"].has_more is True
        assert result["pagination"].total_count == 5


# ---------------------------------------------------------------------------
# factories.py: _apply_filters / _apply_load_only
# ---------------------------------------------------------------------------


class TestApplyFilters:
    def test_none_filters_passes_through(self):
        from sqlalchemy import select

        from tests.conftest import FixtureTask

        stmt = select(FixtureTask)
        result = _apply_filters(stmt, None)
        assert result is stmt

    def test_empty_filters_passes_through(self):
        from sqlalchemy import select

        from tests.conftest import FixtureTask

        stmt = select(FixtureTask)
        result = _apply_filters(stmt, [])
        assert result is stmt


class TestApplyLoadOnly:
    def test_all_relationship_fields_returns_stmt_unchanged(self):
        from sqlalchemy import select

        from tests.conftest import FixtureTask

        stmt = select(FixtureTask)
        # "sprint" and "owner" are relationship fields — no attrs remain
        result = _apply_load_only(stmt, FixtureTask, ["sprint", "owner"])
        assert result is stmt


# ---------------------------------------------------------------------------
# Paginated OneToMany loader
# ---------------------------------------------------------------------------


class TestPageOneToManyLoader:
    @pytest.mark.usefixtures("test_db")
    async def test_basic_pagination(self):
        from tests.conftest import FixtureSprint, FixtureTask

        LoaderCls = create_page_one_to_many_loader(
            source_kls=FixtureSprint,
            rel_name="tasks",
            target_kls=FixtureTask,
            target_fk_col_name="sprint_id",
            sort_field="id",
            pk_col_name="id",
            session_factory=get_test_session_factory(),
        )
        loader = LoaderCls()
        # limit=1, offset=0, total=2 → 1 item returned, 1 item remains → has_more=True.
        # SQL peeks effective_limit+1 rows; len(rows) > limit signals a next page.
        cmd = PageLoadCommand(fk_value=1, page_args=PageArgs(limit=1))
        results = await loader.load_many([cmd])

        assert len(results) == 1
        assert len(results[0]["items"]) == 1
        assert results[0]["pagination"].total_count == 2
        assert results[0]["pagination"].has_more is True

    @pytest.mark.usefixtures("test_db")
    async def test_offset_pagination(self):
        from tests.conftest import FixtureSprint, FixtureTask

        LoaderCls = create_page_one_to_many_loader(
            source_kls=FixtureSprint,
            rel_name="tasks",
            target_kls=FixtureTask,
            target_fk_col_name="sprint_id",
            sort_field="id",
            pk_col_name="id",
            session_factory=get_test_session_factory(),
        )
        loader = LoaderCls()
        cmd = PageLoadCommand(fk_value=1, page_args=PageArgs(limit=1, offset=1))
        results = await loader.load_many([cmd])

        assert len(results[0]["items"]) == 1
        assert results[0]["pagination"].has_more is False

    @pytest.mark.usefixtures("test_db")
    async def test_offset_beyond_total(self):
        from tests.conftest import FixtureSprint, FixtureTask

        LoaderCls = create_page_one_to_many_loader(
            source_kls=FixtureSprint,
            rel_name="tasks",
            target_kls=FixtureTask,
            target_fk_col_name="sprint_id",
            sort_field="id",
            pk_col_name="id",
            session_factory=get_test_session_factory(),
        )
        loader = LoaderCls()
        cmd = PageLoadCommand(fk_value=1, page_args=PageArgs(limit=1, offset=100))
        results = await loader.load_many([cmd])

        assert results[0]["items"] == []
        assert results[0]["pagination"].total_count == 2
        assert results[0]["pagination"].has_more is False

    @pytest.mark.usefixtures("test_db")
    async def test_batch_multiple_parents(self):
        from tests.conftest import FixtureSprint, FixtureTask

        LoaderCls = create_page_one_to_many_loader(
            source_kls=FixtureSprint,
            rel_name="tasks",
            target_kls=FixtureTask,
            target_fk_col_name="sprint_id",
            sort_field="id",
            pk_col_name="id",
            session_factory=get_test_session_factory(),
        )
        loader = LoaderCls()
        pa = PageArgs(limit=10)
        cmds = [
            PageLoadCommand(fk_value=1, page_args=pa),
            PageLoadCommand(fk_value=2, page_args=pa),
        ]
        results = await loader.load_many(cmds)

        assert len(results) == 2
        assert len(results[0]["items"]) == 2
        assert len(results[1]["items"]) == 2

    @pytest.mark.usefixtures("test_db")
    async def test_nonexistent_fk(self):
        from tests.conftest import FixtureSprint, FixtureTask

        LoaderCls = create_page_one_to_many_loader(
            source_kls=FixtureSprint,
            rel_name="tasks",
            target_kls=FixtureTask,
            target_fk_col_name="sprint_id",
            sort_field="id",
            pk_col_name="id",
            session_factory=get_test_session_factory(),
        )
        loader = LoaderCls()
        cmd = PageLoadCommand(fk_value=999, page_args=PageArgs(limit=10))
        results = await loader.load_many([cmd])

        assert results[0]["items"] == []
        assert results[0]["pagination"].total_count == 0


# ---------------------------------------------------------------------------
# Paginated ManyToMany loader
# ---------------------------------------------------------------------------


def _get_m2m_meta():
    from sqlalchemy import inspect

    from tests.conftest import FixtureArticle, FixtureReader

    mapper = inspect(FixtureArticle)
    for rel in mapper.relationships:
        if rel.key == "readers":
            source_col, secondary_local_col = list(rel.synchronize_pairs)[0]
            target_col, secondary_remote_col = list(rel.secondary_synchronize_pairs)[0]
            return {
                "secondary_table": rel.secondary,
                "secondary_local_col_name": secondary_local_col.key,
                "secondary_remote_col_name": secondary_remote_col.key,
                "target_match_col_name": target_col.key,
                "source_kls": FixtureArticle,
                "target_kls": FixtureReader,
            }
    raise RuntimeError("readers relationship not found")


class TestPageManyToManyLoader:
    @pytest.mark.usefixtures("test_db_m2m")
    async def test_basic_pagination(self):
        meta = _get_m2m_meta()

        LoaderCls = create_page_many_to_many_loader(
            source_kls=meta["source_kls"],
            rel_name="readers",
            target_kls=meta["target_kls"],
            secondary_table=meta["secondary_table"],
            secondary_local_col_name=meta["secondary_local_col_name"],
            secondary_remote_col_name=meta["secondary_remote_col_name"],
            target_match_col_name=meta["target_match_col_name"],
            sort_field="id",
            pk_col_name="id",
            session_factory=get_test_session_factory(),
        )
        loader = LoaderCls()
        cmd = PageLoadCommand(fk_value=1, page_args=PageArgs(limit=1))
        results = await loader.load_many([cmd])

        assert len(results) == 1
        assert len(results[0]["items"]) == 1
        assert results[0]["pagination"].total_count == 2
        # limit=1, offset=0, total=2 → 1 item remains → has_more=True.
        assert results[0]["pagination"].has_more is True

    @pytest.mark.usefixtures("test_db_m2m")
    async def test_offset_beyond_total(self):
        meta = _get_m2m_meta()

        LoaderCls = create_page_many_to_many_loader(
            source_kls=meta["source_kls"],
            rel_name="readers",
            target_kls=meta["target_kls"],
            secondary_table=meta["secondary_table"],
            secondary_local_col_name=meta["secondary_local_col_name"],
            secondary_remote_col_name=meta["secondary_remote_col_name"],
            target_match_col_name=meta["target_match_col_name"],
            sort_field="id",
            pk_col_name="id",
            session_factory=get_test_session_factory(),
        )
        loader = LoaderCls()
        cmd = PageLoadCommand(fk_value=1, page_args=PageArgs(limit=1, offset=100))
        results = await loader.load_many([cmd])

        assert results[0]["items"] == []
        assert results[0]["pagination"].total_count == 2
        assert results[0]["pagination"].has_more is False

    @pytest.mark.usefixtures("test_db_m2m")
    async def test_batch_multiple_articles(self):
        meta = _get_m2m_meta()

        LoaderCls = create_page_many_to_many_loader(
            source_kls=meta["source_kls"],
            rel_name="readers",
            target_kls=meta["target_kls"],
            secondary_table=meta["secondary_table"],
            secondary_local_col_name=meta["secondary_local_col_name"],
            secondary_remote_col_name=meta["secondary_remote_col_name"],
            target_match_col_name=meta["target_match_col_name"],
            sort_field="id",
            pk_col_name="id",
            session_factory=get_test_session_factory(),
        )
        loader = LoaderCls()
        pa = PageArgs(limit=10)
        cmds = [
            PageLoadCommand(fk_value=1, page_args=pa),
            PageLoadCommand(fk_value=2, page_args=pa),
        ]
        results = await loader.load_many(cmds)

        assert len(results) == 2
        assert len(results[0]["items"]) == 2
        assert len(results[1]["items"]) == 2

    @pytest.mark.usefixtures("test_db_m2m")
    async def test_nonexistent_fk(self):
        meta = _get_m2m_meta()

        LoaderCls = create_page_many_to_many_loader(
            source_kls=meta["source_kls"],
            rel_name="readers",
            target_kls=meta["target_kls"],
            secondary_table=meta["secondary_table"],
            secondary_local_col_name=meta["secondary_local_col_name"],
            secondary_remote_col_name=meta["secondary_remote_col_name"],
            target_match_col_name=meta["target_match_col_name"],
            sort_field="id",
            pk_col_name="id",
            session_factory=get_test_session_factory(),
        )
        loader = LoaderCls()
        cmd = PageLoadCommand(fk_value=999, page_args=PageArgs(limit=10))
        results = await loader.load_many([cmd])

        assert results[0]["items"] == []
        assert results[0]["pagination"].total_count == 0
