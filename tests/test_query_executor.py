"""Tests for QueryExecutor — GraphQL query execution with DataLoader resolution."""

from __future__ import annotations

import pytest
from graphql import DocumentNode, parse
from sqlmodel import SQLModel, select

from nexusx.decorator import mutation, query
from nexusx.execution.query_executor import QueryExecutor
from nexusx.loader.registry import ErManager, RelationshipInfo
from nexusx.query_parser import FieldSelection, QueryParser
from tests.conftest import (
    FixtureSprint,
    FixtureTask,
    FixtureUser,
    get_test_session_factory,
)

# ──────────────────────────────────────────────────────────
# Helper: build executor + parse selections
# ──────────────────────────────────────────────────────────


def _make_executor(
    entities=None, session_factory=None, enable_pagination=False
) -> QueryExecutor:
    if entities is None:
        entities = [FixtureUser, FixtureSprint, FixtureTask]
    if session_factory is None:
        session_factory = get_test_session_factory()
    registry = ErManager(
        entities=entities,
        session_factory=session_factory,
        enable_pagination=enable_pagination,
    )
    return QueryExecutor(registry, enable_pagination=enable_pagination)


def _get_bound_method(entity_cls, method_name: str):
    """Get the bound classmethod from a @query/@mutation decorated method.

    getattr on a classmethod returns a bound method where cls is already
    bound, so the executor can call method(**args) without passing cls.
    """
    return getattr(entity_cls, method_name)


def _parse(query_str: str) -> tuple[DocumentNode, dict[str, FieldSelection]]:
    """Parse query string once; return (document, selections) for executor."""
    document = parse(query_str)
    return document, QueryParser().parse_document(document)


# ──────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────


class TestQueryExecutorBasic:
    @pytest.mark.usefixtures("test_db")
    async def test_execute_simple_query(self):
        """Basic query execution should return data in correct format."""
        executor = _make_executor()
        session_factory = get_test_session_factory()

        class UserQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureUser))).all())

        method = _get_bound_method(UserQuery, "get_all")
        query_methods = {"users": (FixtureUser, method)}
        document, parsed = _parse("{ users { id name } }")

        result = await executor.execute_query(
            document,
            None,
            None,
            parsed,
            query_methods,
            {},
            [FixtureUser, FixtureSprint, FixtureTask],
        )

        assert "data" in result
        assert "users" in result["data"]
        assert len(result["data"]["users"]) == 2
        names = {u["name"] for u in result["data"]["users"]}
        assert "Alice" in names or "Bob" in names

    @pytest.mark.usefixtures("test_db")
    async def test_execute_mutation(self):
        """Mutation execution should work via mutation_methods."""
        executor = _make_executor()
        session_factory = get_test_session_factory()

        class UserMutation(SQLModel, table=False):
            @mutation
            async def create(cls, name: str):
                async with session_factory() as session:
                    user = FixtureUser(name=name, email=f"{name}@test.com")
                    session.add(user)
                    await session.commit()
                    await session.refresh(user)
                    return user

        method = _get_bound_method(UserMutation, "create")
        mutation_methods = {"createUser": (FixtureUser, method)}
        document, parsed = _parse('mutation { createUser(name: "Eve") { id name } }')

        result = await executor.execute_query(
            document,
            None,
            None,
            parsed,
            {},
            mutation_methods,
            [FixtureUser, FixtureSprint, FixtureTask],
        )

        assert "data" in result
        assert result["data"]["createUser"]["name"] == "Eve"

    async def test_execute_returns_error_on_unknown_field(self):
        """Querying an unknown field should produce an error entry."""
        executor = _make_executor()
        document = parse("{ nonexistent { id } }")

        result = await executor.execute_query(
            document,
            None,
            None,
            {},
            {},
            {},
            [FixtureUser],
        )

        assert "errors" in result
        assert any("nonexistent" in e["message"] for e in result["errors"])

    async def test_execute_handles_exception_in_method(self):
        """Exception in query method should be captured in errors."""
        executor = _make_executor()

        class FailQuery(SQLModel, table=False):
            @query
            async def boom(cls):
                raise RuntimeError("kaboom")

        method = _get_bound_method(FailQuery, "boom")
        query_methods = {"fail": (FixtureUser, method)}
        document, parsed = _parse("{ fail { id } }")

        result = await executor.execute_query(
            document,
            None,
            None,
            parsed,
            query_methods,
            {},
            [FixtureUser],
        )

        assert "errors" in result
        assert any("kaboom" in e["message"] for e in result["errors"])

    async def test_execute_handles_exception_in_method_logs_traceback(self, caplog):
        """When a resolver raises, the full traceback must reach the logger.

        Regression test for the silent-server-bug issue: per-field except at
        query_executor.py:149 used to swallow exceptions into the response
        ``errors`` list with NO log call, making resolver bugs invisible to
        log-based monitoring (Sentry/Loki/CloudWatch).

        The response still has ``{message, path}`` (GraphQL-spec compliant),
        but the server log must also contain the traceback and exception type
        for ops debugging.
        """
        import logging

        # Force the nexusx.execution.query_executor logger to emit at DEBUG
        # so caplog captures it regardless of root config.
        executor = _make_executor()

        class FailQuery(SQLModel, table=False):
            @query
            async def boom(cls):
                # Programming bug — simulates real production resolver errors
                raise AttributeError(
                    "object of type 'NoneType' has no attribute 'split'"
                )

        method = _get_bound_method(FailQuery, "boom")
        query_methods = {"fail": (FixtureUser, method)}
        document, parsed = _parse("{ fail { id } }")

        with caplog.at_level(
            logging.ERROR,
            logger="nexusx.execution.query_executor",
        ):
            result = await executor.execute_query(
                document,
                None,
                None,
                parsed,
                query_methods,
                {},
                [FixtureUser],
            )

        # Response shape unchanged — still GraphQL-spec compliant.
        assert "errors" in result
        err = result["errors"][0]
        assert "NoneType" in err["message"]
        assert err["path"] == ["fail"]

        # Server log must contain the traceback and exception type — these
        # are what ops searches for when triaging "API returned errors".
        log_text = caplog.text
        assert "AttributeError" in log_text, (
            "Exception type missing from log — silent server bug. "
            "query_executor.py must call logger.exception on resolver errors."
        )
        assert "Traceback" in log_text, (
            "Stack trace missing from log — only the message string was "
            "logged. Use logger.exception(...) not logger.error(str(e))."
        )
        assert "split" in log_text, (
            "Exception message missing from log — full context needed."
        )

    async def test_execute_query_with_no_data_returns_empty(self):
        """Query with no matching methods should return empty data."""
        executor = _make_executor()
        document = parse("{ users { id } }")

        result = await executor.execute_query(
            document,
            None,
            None,
            {},
            {},
            {},
            [FixtureUser],
        )

        assert result.get("data") is None or result == {}

    @pytest.mark.usefixtures("test_db")
    async def test_execute_clears_cache_per_request(self):
        """Each execute_query call should clear DataLoader cache."""
        executor = _make_executor()
        session_factory = get_test_session_factory()
        call_count = 0

        class TaskQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                nonlocal call_count
                call_count += 1
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureTask))).all())

        method = _get_bound_method(TaskQuery, "get_all")
        query_methods = {"tasks": (FixtureTask, method)}
        document, parsed = _parse("{ tasks { id title } }")

        entities = [FixtureTask, FixtureUser, FixtureSprint]
        await executor.execute_query(
            document, None, None,
            parsed, query_methods, {}, entities,
        )
        await executor.execute_query(
            document, None, None,
            parsed, query_methods, {}, entities,
        )

        assert call_count == 2


class TestQueryExecutorSerialization:
    async def test_serialize_none_result(self):
        """Query returning None should serialize to null."""
        executor = _make_executor()

        class NoneQuery(SQLModel, table=False):
            @query
            async def get_one(cls):
                return None

        method = _get_bound_method(NoneQuery, "get_one")
        query_methods = {"user": (FixtureUser, method)}
        document, parsed = _parse("{ user { id } }")

        result = await executor.execute_query(
            document, None, None, parsed, query_methods, {}, [FixtureUser]
        )

        assert result["data"]["user"] is None

    @pytest.mark.usefixtures("test_db")
    async def test_serialize_list_result(self):
        """Query returning a list should serialize to list of dicts."""
        executor = _make_executor()
        session_factory = get_test_session_factory()

        class UserQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureUser))).all())

        method = _get_bound_method(UserQuery, "get_all")
        query_methods = {"users": (FixtureUser, method)}
        document, parsed = _parse("{ users { id name } }")

        entities = [FixtureUser, FixtureSprint, FixtureTask]
        result = await executor.execute_query(
            document, None, None,
            parsed, query_methods, {}, entities,
        )

        users = result["data"]["users"]
        assert isinstance(users, list)
        assert len(users) == 2
        assert all(isinstance(u, dict) for u in users)

    @pytest.mark.usefixtures("test_db")
    async def test_execute_with_relationships_resolved(self):
        """Query with nested relationship should resolve via DataLoader."""
        executor = _make_executor()
        session_factory = get_test_session_factory()

        class TaskQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureTask))).all())

        method = _get_bound_method(TaskQuery, "get_all")
        query_methods = {"tasks": (FixtureTask, method)}
        document, parsed = _parse("{ tasks { id title owner { id name } } }")

        result = await executor.execute_query(
            document,
            None,
            None,
            parsed,
            query_methods,
            {},
            [FixtureTask, FixtureUser, FixtureSprint],
        )

        tasks = result["data"]["tasks"]
        assert len(tasks) == 4
        for task in tasks:
            assert "owner" in task
            assert task["owner"] is not None
            assert "name" in task["owner"]

    async def test_paginated_serialization_only_returns_selected_fields(self):
        """Paginated relationship responses should not include unselected items."""
        executor = _make_executor(enable_pagination=True)

        class PageItem(SQLModel, table=False):
            id: int
            name: str

        rel_info = RelationshipInfo(
            name="posts",
            direction="ONETOMANY",
            fk_field="author_id",
            target_entity=PageItem,
            is_list=True,
            loader=object,
        )
        child_sel = QueryParser().parse("{ posts { pagination { total_count } } }")["posts"]

        result = executor._serialize_relationship_value(
            value={
                "items": [PageItem(id=1, name="A")],
                "pagination": {"total_count": 1, "has_more": False},
            },
            rel_info=rel_info,
            child_sel=child_sel,
        )

        assert "items" not in result
        assert result["pagination"] == {"total_count": 1}

    def test_extract_page_args_rejects_negative_values(self):
        """Negative pagination arguments should fail fast."""
        executor = _make_executor(enable_pagination=True)

        class Rel:
            default_page_size = 20
            max_page_size = 100

        with pytest.raises(ValueError, match="limit must be greater than or equal to 0"):
            executor._extract_page_args(
                FieldSelection(arguments={"limit": -1}),
                Rel(),
            )

        with pytest.raises(ValueError, match="offset must be greater than or equal to 0"):
            executor._extract_page_args(
                FieldSelection(arguments={"offset": -1}),
                Rel(),
            )


# ──────────────────────────────────────────────────────────
# Split loader by type — GraphQL e2e tests
# ──────────────────────────────────────────────────────────


def _make_split_executor(session_factory=None) -> QueryExecutor:
    """Build executor with split_loader_by_type=True."""
    if session_factory is None:
        session_factory = get_test_session_factory()
    registry = ErManager(
        entities=[FixtureUser, FixtureSprint, FixtureTask],
        session_factory=session_factory,
        split_loader_by_type=True,
    )
    return QueryExecutor(registry)


class TestQueryExecutorSplitMode:
    """GraphQL end-to-end tests for split_loader_by_type."""

    @pytest.mark.usefixtures("test_db")
    async def test_split_mode_returns_correct_results(self):
        """Split mode should execute a relationship query correctly."""
        executor = _make_split_executor()
        session_factory = get_test_session_factory()

        class TaskQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureTask))).all())

        method = _get_bound_method(TaskQuery, "get_all")
        query_methods = {"tasks": (FixtureTask, method)}
        document, parsed = _parse("{ tasks { id title owner { id name } } }")

        result = await executor.execute_query(
            document,
            None, None, parsed, query_methods, {},
            [FixtureTask, FixtureUser, FixtureSprint],
        )

        tasks = result["data"]["tasks"]
        assert len(tasks) == 4
        for task in tasks:
            assert task["owner"] is not None
            assert "id" in task["owner"]
            assert "name" in task["owner"]

    @pytest.mark.usefixtures("test_db")
    async def test_split_mode_separate_loaders_for_different_selections(self):
        """Two root queries accessing the same relationship with different
        field selections should create separate loader instances in split mode,
        each with its own _query_meta."""
        executor = _make_split_executor()
        session_factory = get_test_session_factory()
        registry = executor._registry

        class TaskQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureTask))).all())

        method = _get_bound_method(TaskQuery, "get_all")
        query_methods = {
            "tasks": (FixtureTask, method),
            "otherTasks": (FixtureTask, method),
        }
        gql = "{ tasks { owner { id name } } otherTasks { owner { id email } } }"
        document, parsed = _parse(gql)

        result = await executor.execute_query(
            document, None, None, parsed, query_methods, {},
            [FixtureTask, FixtureUser, FixtureSprint],
        )

        # Verify results are correct for both root fields
        for task in result["data"]["tasks"]:
            assert task["owner"] is not None
            assert "name" in task["owner"]
        for task in result["data"]["otherTasks"]:
            assert task["owner"] is not None
            assert "email" in task["owner"]

        # Verify registry has 2 separate loader instances for owner M2O
        rel_info = registry.get_relationship(FixtureTask, "owner")
        loader_cls = rel_info.loader
        inner = registry._loader_instances[loader_cls]
        assert isinstance(inner, dict)  # split mode: nested dict
        assert len(inner) == 2

        type_keys = set(inner.keys())
        assert frozenset({"id", "name"}) in type_keys
        assert frozenset({"id", "email"}) in type_keys

        # Each loader has its own _query_meta matching its type_key
        for tk, loader in inner.items():
            meta_fields = set(loader._query_meta["fields"])
            assert meta_fields == tk

    @pytest.mark.usefixtures("test_db")
    async def test_split_mode_nested_relationships(self):
        """Split mode with nested relationships (sprint -> tasks -> owner)."""
        executor = _make_split_executor()
        session_factory = get_test_session_factory()

        class SprintQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureSprint))).all())

        method = _get_bound_method(SprintQuery, "get_all")
        query_methods = {"sprints": (FixtureSprint, method)}
        document, parsed = _parse(
            "{ sprints { id name tasks { id title owner { id name } } } }"
        )

        result = await executor.execute_query(
            document,
            None, None, parsed, query_methods, {},
            [FixtureTask, FixtureUser, FixtureSprint],
        )

        sprints = result["data"]["sprints"]
        assert len(sprints) == 2
        for sprint in sprints:
            assert "tasks" in sprint
            for task in sprint["tasks"]:
                assert task["owner"] is not None
                assert "name" in task["owner"]

    @pytest.mark.usefixtures("test_db")
    async def test_default_mode_single_loader_with_merged_fields(self):
        """Default mode uses a single shared loader instance whose _query_meta
        fields reflect the queried selection."""
        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
            # split_loader_by_type=False (default)
        )
        executor = QueryExecutor(registry)

        class TaskQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureTask))).all())

        method = _get_bound_method(TaskQuery, "get_all")
        query_methods = {"tasks": (FixtureTask, method)}
        document, parsed = _parse("{ tasks { owner { id name } } }")

        await executor.execute_query(
            document,
            None, None, parsed, query_methods, {},
            [FixtureTask, FixtureUser, FixtureSprint],
        )

        # Default mode: flat cache, single instance per loader_cls
        rel_info = registry.get_relationship(FixtureTask, "owner")
        loader_cls = rel_info.loader
        instance = registry._loader_instances[loader_cls]
        assert not isinstance(instance, dict)
        meta_fields = set(instance._query_meta["fields"])
        assert meta_fields == {"id", "name"}


# ──────────────────────────────────────────────────────────
# Additional coverage tests
# ──────────────────────────────────────────────────────────


class TestBuildFieldJobsEdgeCases:
    def test_empty_sub_fields_returns_no_jobs(self):
        """child_sel with empty sub_fields should produce no jobs."""
        executor = _make_executor()
        rel_info = executor._registry.get_relationship(FixtureTask, "owner")
        assert rel_info is not None

        # FieldSelection with no sub_fields (only scalar selected)
        child_sel = FieldSelection(name="owner")
        jobs = executor._build_field_jobs(
            [FixtureTask(id=1, title="T", sprint_id=1, owner_id=1)],
            FixtureTask,
            FieldSelection(name="root", sub_fields={"owner": child_sel}),
        )
        assert jobs == []

    def test_all_none_fk_values_returns_no_jobs(self):
        """Parents with all-None FK values should produce no jobs."""
        executor = _make_executor()
        # FixtureTask with owner_id=None (FK not set)
        task = FixtureTask(id=99, title="orphan", sprint_id=1, owner_id=None)
        jobs = executor._build_field_jobs(
            [task],
            FixtureTask,
            FieldSelection(name="root", sub_fields={
                "owner": FieldSelection(name="owner", sub_fields={"id": FieldSelection(name="id")}),
            }),
        )
        assert jobs == []

    @pytest.mark.usefixtures("test_db")
    async def test_resolve_result_with_none(self):
        """_resolve_result should handle None result gracefully."""
        executor = _make_executor()
        # Should not raise
        await executor._resolve_result(None, FixtureUser, FieldSelection(name="root"))

    def test_pagination_items_without_sub_fields_produces_job_with_empty_sel(self):
        """Paginated field with only pagination selected still produces a job
        because child_sel.sub_fields is non-empty (has 'pagination')."""
        executor = _make_executor(enable_pagination=True)
        child_sel = FieldSelection(
            name="tasks",
            sub_fields={
                "pagination": FieldSelection(name="pagination"),
            },
        )
        jobs = executor._build_field_jobs(
            [FixtureSprint(id=1, name="S1")],
            FixtureSprint,
            FieldSelection(name="root", sub_fields={"tasks": child_sel}),
        )
        # A job is created because child_sel.sub_fields is non-empty
        assert len(jobs) == 1


class TestQueryExecutorPagination:
    @pytest.mark.usefixtures("test_db")
    async def test_paginated_query_e2e(self):
        """End-to-end paginated query should return items + pagination metadata."""
        executor = _make_executor(enable_pagination=True)
        session_factory = get_test_session_factory()

        class SprintQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureSprint))).all())

        method = _get_bound_method(SprintQuery, "get_all")
        query_methods = {"sprints": (FixtureSprint, method)}
        gql = "{ sprints { id name tasks { items { id title } pagination { total_count has_more } } } }"
        document, parsed = _parse(gql)

        result = await executor.execute_query(
            document, None, None, parsed, query_methods, {},
            [FixtureTask, FixtureUser, FixtureSprint],
        )

        sprints = result["data"]["sprints"]
        assert len(sprints) == 2
        for sprint in sprints:
            page = sprint["tasks"]
            assert "items" in page
            assert len(page["items"]) == 2
            assert "pagination" in page
            assert page["pagination"]["total_count"] == 2

    @pytest.mark.usefixtures("test_db")
    async def test_paginated_query_respects_limit(self):
        """limit argument should be propagated to paginated loader."""
        executor = _make_executor(enable_pagination=True)
        session_factory = get_test_session_factory()

        class SprintQuery(SQLModel, table=False):
            @query
            async def get_all(cls):
                async with session_factory() as session:
                    return list((await session.exec(select(FixtureSprint))).all())

        method = _get_bound_method(SprintQuery, "get_all")
        query_methods = {"sprints": (FixtureSprint, method)}
        gql = "{ sprints { id name tasks(limit: 1) { items { id title } pagination { total_count has_more } } } }"
        document, parsed = _parse(gql)

        result = await executor.execute_query(
            document, None, None, parsed, query_methods, {},
            [FixtureTask, FixtureUser, FixtureSprint],
        )

        sprints = result["data"]["sprints"]
        for sprint in sprints:
            page = sprint["tasks"]
            assert len(page["items"]) == 1
            assert page["pagination"]["total_count"] == 2
            # limit=1, offset=0, total=2 → 1 item remains → has_more=True.
            assert page["pagination"]["has_more"] is True

    @pytest.mark.usefixtures("test_db")
    async def test_custom_relationship_with_pagination_enabled(self):
        """Custom relationships should query normally when enable_pagination=True."""
        from nexusx.relationship import Relationship

        session_factory = get_test_session_factory()

        # Custom loader: given FixtureSprint ids, return their tasks
        async def _load_sprint_tasks(keys):
            async with session_factory() as session:
                result = await session.exec(
                    select(FixtureTask).where(FixtureTask.sprint_id.in_(keys))
                )
                tasks = list(result.all())
            grouped = {k: [] for k in keys}
            for t in tasks:
                grouped[t.sprint_id].append(t)
            return [grouped[k] for k in keys]

        # Add custom relationship to FixtureSprint at runtime
        FixtureSprint.__relationships__ = [
            Relationship(
                fk="id",
                target=list[FixtureTask],
                name="custom_tasks",
                loader=_load_sprint_tasks,
            )
        ]

        try:
            executor = _make_executor(
                entities=[FixtureSprint, FixtureTask],
                session_factory=session_factory,
                enable_pagination=True,
            )

            class SprintQuery(SQLModel, table=False):
                @query
                async def get_all(cls):
                    async with session_factory() as session:
                        return list((await session.exec(select(FixtureSprint))).all())

            method = _get_bound_method(SprintQuery, "get_all")
            query_methods = {"sprints": (FixtureSprint, method)}
            # Custom relationship field — no pagination wrapper, just a plain list
            gql = "{ sprints { id name custom_tasks { id title } } }"
            document, parsed = _parse(gql)

            result = await executor.execute_query(
                document, None, None, parsed, query_methods, {},
                [FixtureSprint, FixtureTask],
            )

            sprints = result["data"]["sprints"]
            assert len(sprints) == 2
            for sprint in sprints:
                assert "custom_tasks" in sprint
                assert isinstance(sprint["custom_tasks"], list)
                assert len(sprint["custom_tasks"]) == 2
        finally:
            del FixtureSprint.__relationships__


class TestQueryExecutorSerializationExtras:
    def test_serialize_without_field_sel_uses_model_dump(self):
        """_serialize with no sub_fields should fall back to model_dump."""
        executor = _make_executor()
        user = FixtureUser(id=1, name="Alice", email="alice@test.com")
        result = executor._serialize(user, FixtureUser, None)
        assert isinstance(result, dict)
        assert result["id"] == 1

    def test_serialize_none_result(self):
        """_serialize with None result should return None."""
        executor = _make_executor()
        assert executor._serialize(None, FixtureUser, None) is None

    def test_serialize_list_result(self):
        """_serialize with list result should return list of dicts."""
        executor = _make_executor()
        users = [
            FixtureUser(id=1, name="Alice", email="a@t.com"),
            FixtureUser(id=2, name="Bob", email="b@t.com"),
        ]
        result = executor._serialize(users, FixtureUser, None)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_serialize_item_returns_none_for_none(self):
        """_serialize_item should return None-filtered result (via _serialize)."""
        executor = _make_executor()
        # _serialize handles None at top level
        assert executor._serialize(None, FixtureUser, None) is None

    def test_serialize_item_passes_through_dict(self):
        """_serialize_item should pass through dict values."""
        executor = _make_executor()
        assert executor._serialize_item({"id": 1}, FixtureUser, None) == {"id": 1}

    def test_serialize_relationship_value_none(self):
        """_serialize_relationship_value should return None for None value."""
        executor = _make_executor()
        rel_info = RelationshipInfo(
            name="owner", direction="MANYTOONE", fk_field="owner_id",
            target_entity=FixtureUser, is_list=False, loader=object,
        )
        assert executor._serialize_relationship_value(
            None, rel_info, FieldSelection(name="owner")
        ) is None

    def test_get_fk_fields(self):
        """_get_fk_fields should return FK field names."""
        executor = _make_executor()
        fk_fields = executor._get_fk_fields(FixtureTask)
        assert "sprint_id" in fk_fields
        assert "owner_id" in fk_fields

    def test_get_relationship_names(self):
        """_get_relationship_names should return relationship field names."""
        executor = _make_executor()
        rel_names = executor._get_relationship_names(FixtureTask)
        assert "sprint" in rel_names
        assert "owner" in rel_names

    def test_paginated_serialization_with_pydantic_pagination(self):
        """Pagination as Pydantic model should be serialized via model_dump."""
        from nexusx.loader.pagination import Pagination

        executor = _make_executor(enable_pagination=True)
        rel_info = RelationshipInfo(
            name="tasks", direction="ONETOMANY", fk_field="sprint_id",
            target_entity=FixtureTask, is_list=True, loader=object,
        )
        child_sel = QueryParser().parse(
            "{ posts { pagination { total_count has_more } } }"
        )["posts"]

        result = executor._serialize_relationship_value(
            value={
                "items": [],
                "pagination": Pagination(has_more=False, total_count=5),
            },
            rel_info=rel_info,
            child_sel=child_sel,
        )
        assert result["pagination"]["total_count"] == 5
        assert result["pagination"]["has_more"] is False

    def test_paginated_serialization_all_pagination_fields(self):
        """Pagination with no sub-field filter should return all fields."""
        executor = _make_executor(enable_pagination=True)
        rel_info = RelationshipInfo(
            name="tasks", direction="ONETOMANY", fk_field="sprint_id",
            target_entity=FixtureTask, is_list=True, loader=object,
        )
        # pagination selected but no sub_fields → return all pagination fields
        child_sel = FieldSelection(
            name="tasks",
            sub_fields={"pagination": FieldSelection(name="pagination")},
        )

        result = executor._serialize_relationship_value(
            value={
                "items": [],
                "pagination": {"total_count": 3, "has_more": True},
            },
            rel_info=rel_info,
            child_sel=child_sel,
        )
        assert result["pagination"] == {"total_count": 3, "has_more": True}
