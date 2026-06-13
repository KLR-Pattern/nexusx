"""DefineSubset — generate independent Pydantic DTO models from SQLModel entities.

Creates pure Pydantic BaseModel classes from SQLModel entities, selecting
specific fields while hiding FK columns and relationship attributes.
The generated DTO is fully decoupled from the ORM layer.

Usage:
    from sqlmodel import SQLModel, Field, Relationship
    from nexusx import DefineSubset

    class User(SQLModel, table=True):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        email: str

    class Post(SQLModel, table=True):
        id: int | None = Field(default=None, primary_key=True)
        title: str
        author_id: int = Field(foreign_key="user.id")
        author: User | None = Relationship(back_populates="posts")

    class UserSummary(DefineSubset):
        __subset__ = (User, ('id', 'name'))

    class PostSummary(DefineSubset):
        __subset__ = (Post, ('id', 'title', 'author_id'))
        author: UserSummary | None = None
"""

from __future__ import annotations

import copy
from typing import Any, Literal, get_args, get_origin  # noqa: F401 (Literal used in annotations)

from pydantic import BaseModel, create_model, model_validator
from pydantic.fields import FieldInfo
from sqlmodel import SQLModel

from nexusx.resolver import POST_PREFIX, RESOLVE_PREFIX  # noqa: F401

# ──────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────

SUBSET_DEFINITION = "__subset__"
SUBSET_REFERENCE = "__nexusx_subset_source__"

# ──────────────────────────────────────────────────────────
# DTO ↔ Entity mapping registry
# ──────────────────────────────────────────────────────────

# Maps DTO class → source SQLModel entity class
_subset_registry: dict[type[BaseModel], type[SQLModel]] = {}


def get_subset_source(dto_class: type[BaseModel]) -> type[SQLModel] | None:
    """Get the source SQLModel entity class for a DTO."""
    return _subset_registry.get(dto_class)


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────

def _get_relationship_names(entity: type[SQLModel]) -> set[str]:
    """Get relationship field names from a SQLModel entity via SQLAlchemy inspection."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.exc import NoInspectionAvailable

    try:
        mapper = sa_inspect(entity)
        if mapper and hasattr(mapper, "relationships"):
            return {rel.key for rel in mapper.relationships}
    except NoInspectionAvailable:
        pass
    return set()


def _get_all_relationship_names(entity: type[SQLModel]) -> set[str]:
    """Get both ORM and custom relationship names from a SQLModel entity."""
    from nexusx.relationship import get_custom_relationships

    orm_names = _get_relationship_names(entity)
    custom_names = {r.name for r in get_custom_relationships(entity)}
    return orm_names | custom_names


def _get_pk_field_names(entity: type[SQLModel]) -> list[str]:
    """Get primary key field names from a SQLModel entity."""
    pk_names: list[str] = []
    for field_name, field_info in entity.model_fields.items():
        if getattr(field_info, "primary_key", None) is True:
            pk_names.append(field_name)
    return pk_names


def _get_fk_field_names(entity: type[SQLModel]) -> list[str]:
    """Get foreign key field names from a SQLModel entity."""
    fk_names: list[str] = []
    for field_name, field_info in entity.model_fields.items():
        if _is_fk_field(field_info):
            fk_names.append(field_name)
    return fk_names


def _get_sqlmodel_scalar_fields(entity: type[SQLModel]) -> dict[str, FieldInfo]:
    """Get only scalar fields from a SQLModel entity (exclude relationships and FK fields)."""
    relationship_names = _get_relationship_names(entity)

    # Get FK field names
    fk_fields: set[str] = set()
    for field_name, field_info in entity.model_fields.items():
        if hasattr(field_info, "foreign_key") and isinstance(field_info.foreign_key, str):
            fk_fields.add(field_name)
        if hasattr(field_info, "metadata"):
            for meta in field_info.metadata:
                if hasattr(meta, "foreign_key") and isinstance(meta.foreign_key, str):
                    fk_fields.add(field_name)

    scalar_fields = {}
    for field_name, field_info in entity.model_fields.items():
        if field_name not in relationship_names and field_name not in fk_fields:
            scalar_fields[field_name] = field_info

    return scalar_fields


def _extract_field_infos(
    entity: type[SQLModel],
    field_names: list[str],
    include_fks: bool = True,
) -> dict[str, tuple[Any, FieldInfo]]:
    """Extract field definitions from a SQLModel entity for subset creation.

    Args:
        entity: Source SQLModel entity class.
        field_names: Field names to include.
        include_fks: Whether to include FK fields (with exclude=True for hiding).

    Returns:
        Dict of field_name -> (annotation, FieldInfo) for create_model.
    """
    relationship_names = _get_relationship_names(entity)

    field_definitions: dict[str, tuple[Any, FieldInfo]] = {}

    for field_name in field_names:
        # Skip relationship fields — handled via implicit auto-loading
        # or manual resolve
        if field_name in relationship_names:
            continue

        field = entity.model_fields.get(field_name)
        if field is None:
            raise AttributeError(
                f'field "{field_name}" does not exist in {entity.__name__}'
            )

        # Check if this is a FK field
        is_fk = _is_fk_field(field)

        if is_fk and not include_fks:
            continue

        # Deep copy to avoid mutating the source entity's FieldInfo
        new_field = copy.deepcopy(field)

        if is_fk:
            # Remove FK metadata to prevent Pydantic-SQLModel interference
            new_field.metadata = [
                m for m in new_field.metadata
                if not hasattr(m, "foreign_key")
            ]

        field_definitions[field_name] = (new_field.annotation, new_field)

    return field_definitions


def _is_fk_field(field: FieldInfo) -> bool:
    """Check if a FieldInfo represents a foreign key field."""
    if hasattr(field, "foreign_key") and isinstance(field.foreign_key, str):
        return True
    if hasattr(field, "metadata"):
        for meta in field.metadata:
            if hasattr(meta, "foreign_key") and isinstance(meta.foreign_key, str):
                return True
    return False


def _validate_subset_fields(fields: Any) -> None:
    """Validate that field names are a list/tuple of unique strings."""
    if not isinstance(fields, (list, tuple)):
        raise TypeError("fields must be a list or tuple of field names")

    seen: set[str] = set()
    for f in fields:
        if not isinstance(f, str):
            raise TypeError("each field name must be a string")
        if f in seen:
            raise ValueError(f'duplicate field name "{f}" in subset fields')
        seen.add(f)


def _get_namespace_annotations(namespace: dict[str, Any]) -> dict[str, Any]:
    """Extract annotations from class namespace, compatible with Python 3.14+.

    Python 3.14 (PEP 649/749) stores annotations lazily in __annotate_func__
    and sets __annotations__ to None in the class body namespace.
    """
    annotations = namespace.get("__annotations__")
    if isinstance(annotations, dict):
        return annotations
    annotate_func = namespace.get("__annotate_func__")
    if annotate_func is not None:
        return annotate_func(1)
    return {}


def _extract_extra_fields(
    namespace: dict[str, Any],
    subset_field_names: set[str],
) -> tuple[dict[str, tuple[Any, Any]], dict[str, Any]]:
    """Extract extra field definitions from the DefineSubset class body.

    Returns a tuple of:
    - extras: new fields not in the subset (e.g., relationship fields, derived fields)
    - overrides: annotations for subset fields (e.g., ExposeAs/SendTo metadata)

    Subset fields can be re-annotated with metadata like ExposeAs/SendTo
    without conflicting with the subset definition.
    """
    annotations: dict[str, Any] = _get_namespace_annotations(namespace)
    extras: dict[str, tuple[Any, Any]] = {}
    overrides: dict[str, Any] = {}

    for fname, anno in annotations.items():
        if fname == SUBSET_DEFINITION:
            continue
        if fname in subset_field_names:
            overrides[fname] = anno
            continue
        default = namespace.get(fname, ...)
        extras[fname] = (anno, default)

    return extras, overrides


def _extract_methods(namespace: dict[str, Any]) -> dict[str, Any]:
    """Extract resolve_* and post_* methods from the class namespace."""
    methods = {}
    for key, value in namespace.items():
        if callable(value) and (
            key.startswith(RESOLVE_PREFIX) or key.startswith(POST_PREFIX)
        ):
            methods[key] = value
    return methods


def _unwrap_annotation(anno: Any) -> type | None:
    """Unwrap Optional / list / Annotated to the innermost concrete type.

    Returns the innermost type if it's a real class, otherwise None.
    """
    import typing

    # Resolve string annotations lazily — can't resolve here
    if isinstance(anno, str):
        return None

    origin = get_origin(anno)

    # Unwrap Annotated[X, ...] → X
    if origin is typing.Annotated:
        args = get_args(anno)
        if args:
            return _unwrap_annotation(args[0])
        return None

    # Unwrap Union / Optional[X, None] → X
    if origin is type(None):
        return None
    args = get_args(anno)
    if args:
        non_none = [a for a in args if a is not type(None)]
        if non_none and len(non_none) == 1 and len(args) > 1:
            return _unwrap_annotation(non_none[0])

    # Unwrap list[X] → X
    if origin is list:
        args = get_args(anno)
        if args:
            return _unwrap_annotation(args[0])

    # Base case: concrete type
    if isinstance(anno, type):
        return anno

    return None


def _validate_extra_field_types(
    extra_fields: dict[str, tuple[Any, Any]],
    entity_kls: type[SQLModel],
    global_ns: dict[str, Any],
    local_ns: dict[str, Any],
) -> None:
    """Validate that extra fields matching relationships don't use raw SQLModel types."""

    rel_names = _get_all_relationship_names(entity_kls)

    for fname, (anno, _default) in extra_fields.items():
        if fname not in rel_names:
            continue

        # Resolve string annotation
        resolved = anno
        if isinstance(resolved, str):
            try:
                resolved = eval(resolved, global_ns, local_ns)  # noqa: S307
            except NameError:
                continue

        inner_type = _unwrap_annotation(resolved)
        if inner_type is not None and issubclass(inner_type, SQLModel):
            raise TypeError(
                f"Relationship field '{fname}' in DefineSubset must use a DTO type "
                f"(DefineSubset subclass), not the raw SQLModel entity "
                f"'{inner_type.__name__}'. "
                f"Define a DTO class first, e.g.:\n"
                f"    class {inner_type.__name__}DTO(DefineSubset):\n"
                f"        __subset__ = ({inner_type.__name__}, (...))\n"
                f"Then use: {fname}: {inner_type.__name__}DTO | None = None"
            )


def _validate_omitted_fk_not_needed(
    entity_kls: type[SQLModel],
    subset_info: Any,
    extra_fields: dict[str, tuple[Any, Any]],
) -> None:
    """Raise if a FK is in omit_fields but a relationship extra field needs it."""
    if not isinstance(subset_info, SubsetConfig) or not subset_info.omit_fields:
        return

    fk_names = set(_get_fk_field_names(entity_kls))
    omitted_fks = set(subset_info.omit_fields) & fk_names
    if not omitted_fks:
        return

    rel_names = _get_all_relationship_names(entity_kls)
    extra_rel_fields = set(extra_fields.keys()) & rel_names
    if not extra_rel_fields:
        return

    for fk in omitted_fks:
        # Convention: owner_id → owner, sprint_id → sprint
        rel_name = fk.removesuffix("_id")
        if rel_name in extra_rel_fields:
            raise ValueError(
                f"Cannot omit FK field '{fk}' from {entity_kls.__name__} subset: "
                f"relationship field '{rel_name}' requires it for DataLoader resolution. "
                f"Either remove '{rel_name}' from the DTO or remove '{fk}' from omit_fields."
            )


# ──────────────────────────────────────────────────────────
# SubsetMeta metaclass
# ──────────────────────────────────────────────────────────

class SubsetConfig(BaseModel):
    """Declarative configuration for DefineSubset field selection and metadata.

    Used as an alternative to the tuple syntax for ``__subset__``::

        __subset__ = SubsetConfig(
            kls=User,
            fields=['id', 'name'],
            expose_as=[('name', 'user_name')],
        )

    Args:
        kls: Source SQLModel entity class.
        fields: Field names to include, or ``"all"`` for every field.
            Mutually exclusive with *omit_fields*.
        omit_fields: Field names to exclude.  Mutually exclusive with *fields*.
        excluded_fields: Fields that exist on the DTO but are hidden from
            serialization (``Field(exclude=True)``).
        expose_as: List of ``(field_name, alias)`` pairs.  Equivalent to
            annotating the field with ``ExposeAs(alias)`` in the class body.
        send_to: List of ``(field_name, collector_name)`` pairs.  Equivalent
            to annotating the field with ``SendTo(collector_name)``.
    """

    kls: type
    # fields and omit_fields are exclusive
    # Use fields="all" to include all fields from the entity
    fields: list[str] | str | None = None
    omit_fields: list[str] | None = None
    # set Field(exclude=True) for these fields
    excluded_fields: list[str] | None = None
    expose_as: list[tuple[str, str]] | None = None
    send_to: list[tuple[str, str | tuple[str, ...]]] | None = None

    @model_validator(mode="after")
    def _validate_config(self) -> SubsetConfig:
        if self.fields is not None and self.omit_fields is not None:
            raise ValueError("fields and omit_fields are exclusive")
        if self.fields is None and self.omit_fields is None:
            raise ValueError("fields or omit_fields must be provided")
        return self


def _apply_config_modifiers(
    config: SubsetConfig,
    field_definitions: dict[str, tuple[Any, Any]],
) -> None:
    """Apply SubsetConfig ``excluded_fields`` in-place.

    Sets ``FieldInfo.exclude = True`` on matching fields.
    """
    if not config.excluded_fields:
        return

    excluded_set = set(config.excluded_fields)

    for fname, (annotation, field_value) in list(field_definitions.items()):
        if fname not in excluded_set:
            continue

        if isinstance(field_value, FieldInfo):
            new_fi = copy.deepcopy(field_value)
        else:
            new_fi = FieldInfo(default=field_value)

        new_fi.exclude = True
        field_definitions[fname] = (annotation, new_fi)


def _build_config_overrides(config: SubsetConfig) -> dict[str, Any]:
    """Build synthetic override annotations from SubsetConfig expose_as/send_to.

    Returns a dict of fname -> Annotated[tuple, metadata...] that will be
    merged through the existing override merge path.  Using ``Annotated[tuple, ...]``
    as a placeholder type — the override merge resolves the real annotation
    from the class body and replaces ``tuple`` with the actual type.
    """
    from typing import Annotated

    from nexusx.context import ExposeAs, SendTo

    overrides: dict[str, Any] = {}

    expose_map: dict[str, str] = (
        {name: alias for name, alias in config.expose_as}
        if config.expose_as
        else {}
    )
    send_map: dict[str, str | tuple[str, ...]] = (
        {name: target for name, target in config.send_to}
        if config.send_to
        else {}
    )

    for fname, alias in expose_map.items():
        extras = [ExposeAs(alias)]
        if fname in send_map:
            extras.append(SendTo(send_map[fname]))
        overrides[fname] = Annotated[(tuple, *extras)]  # type: ignore[misc]

    for fname, target in send_map.items():
        if fname not in overrides:
            overrides[fname] = Annotated[tuple, SendTo(target)]  # type: ignore[misc]

    return overrides


class SubsetMeta(type):
    """Metaclass that transforms a DefineSubset class definition into a Pydantic BaseModel.

    Reads ``__subset__ = (Entity, ('field1', 'field2'))`` or
    ``__subset__ = SubsetConfig(...)`` and generates a pure Pydantic model
    with the selected fields from the SQLModel entity.
    """

    def __new__(cls, name: str, bases: tuple, namespace: dict, **kwargs):
        subset_info = namespace.get(SUBSET_DEFINITION)

        # Allow defining the marker class itself
        if name == "DefineSubset" and not any(
            isinstance(b, SubsetMeta) for b in bases
        ):
            return super().__new__(cls, name, bases, namespace, **kwargs)

        if not subset_info:
            raise ValueError(
                f"Class {name} must define {SUBSET_DEFINITION} = (Entity, fields)"
            )

        entity_kls, subset_fields, auto_excluded = cls._resolve_subset_info(subset_info)
        field_definitions, extra_fields, override_annotations = cls._build_field_definitions(
            entity_kls, subset_fields, namespace, auto_excluded, subset_info,
        )
        global_ns = cls._build_global_ns(namespace)
        local_ns = cls._build_local_ns(global_ns)
        cls._merge_overrides(field_definitions, override_annotations, global_ns, namespace)
        if isinstance(subset_info, SubsetConfig):
            cls._merge_config_overrides(field_definitions, subset_info, local_ns, namespace)

        _validate_extra_field_types(extra_fields, entity_kls, global_ns, namespace)
        _validate_omitted_fk_not_needed(
            entity_kls, subset_info, extra_fields,
        )

        return cls._create_subset_class(
            name, field_definitions, subset_fields, entity_kls, namespace,
            auto_excluded,
        )

    @staticmethod
    def _resolve_subset_info(
        subset_info: Any,
    ) -> tuple[type[SQLModel], list[str], set[str]]:
        """Parse __subset__ into (entity_kls, subset_fields, auto_excluded_pk)."""
        if isinstance(subset_info, SubsetConfig):
            entity_kls = subset_info.kls
            if subset_info.fields is not None:
                if subset_info.fields == "all":
                    subset_fields = list(entity_kls.model_fields.keys())
                else:
                    subset_fields = list(subset_info.fields)
            else:
                all_fields = list(entity_kls.model_fields.keys())
                omit_set = set(subset_info.omit_fields)
                subset_fields = [f for f in all_fields if f not in omit_set]
        else:
            if not isinstance(subset_info, tuple) or len(subset_info) != 2:
                raise ValueError(
                    f"{SUBSET_DEFINITION} must be a tuple of (EntityClass, field_names) "
                    f"or a SubsetConfig instance"
                )
            entity_kls, subset_fields = subset_info

        if not (isinstance(entity_kls, type) and issubclass(entity_kls, SQLModel)):
            raise TypeError(
                f"Source entity must be a SQLModel class, got {entity_kls}"
            )

        _validate_subset_fields(subset_fields)
        subset_fields = list(subset_fields)

        # Auto-include PK fields for DataLoader key resolution (ONETOMANY loading).
        auto_excluded: set[str] = set()
        existing_set = set(subset_fields)
        user_omit: set[str] = set()
        if isinstance(subset_info, SubsetConfig) and subset_info.omit_fields:
            user_omit = set(subset_info.omit_fields)

        pk_fields = _get_pk_field_names(entity_kls)
        for pk in pk_fields:
            if pk not in existing_set:
                subset_fields.append(pk)
                existing_set.add(pk)
                if pk in user_omit:
                    auto_excluded.add(pk)

        # Auto-include FK fields for DataLoader key resolution (relationship loading).
        # FK fields in user_omit are skipped — validation later checks for conflicts.
        fk_fields = _get_fk_field_names(entity_kls)
        for fk in fk_fields:
            if fk in user_omit:
                continue
            if fk not in existing_set:
                subset_fields.append(fk)
                existing_set.add(fk)
                auto_excluded.add(fk)

        return entity_kls, subset_fields, auto_excluded

    @staticmethod
    def _build_field_definitions(
        entity_kls: type[SQLModel],
        subset_fields: list[str],
        namespace: dict,
        auto_excluded: set[str],
        subset_info: Any,
    ) -> tuple[dict[str, tuple[Any, Any]], dict[str, tuple[Any, Any]], dict[str, Any]]:
        """Extract and merge field definitions from entity + class body.

        Returns (field_definitions, extra_fields, override_annotations).
        """
        field_infos = _extract_field_infos(entity_kls, subset_fields)
        extra_fields, override_annotations = _extract_extra_fields(
            namespace, set(subset_fields),
        )

        field_definitions: dict[str, tuple[Any, Any]] = {}
        field_definitions.update(field_infos)
        field_definitions.update(extra_fields)

        # Hide auto-included PK/FK fields from serialization
        for field_name in auto_excluded:
            if field_name in field_definitions:
                _anno, fi = field_definitions[field_name]
                if isinstance(fi, FieldInfo):
                    new_fi = copy.deepcopy(fi)
                    new_fi.exclude = True
                    # Make auto-included FK fields optional with default None
                    if _is_fk_field(fi):
                        from typing import Union as _Union

                        _anno = _Union[_anno, type(None)]
                        new_fi.default = None
                    field_definitions[field_name] = (_anno, new_fi)

        if isinstance(subset_info, SubsetConfig):
            _apply_config_modifiers(subset_info, field_definitions)

        return field_definitions, extra_fields, override_annotations

    @staticmethod
    def _build_global_ns(namespace: dict) -> dict[str, Any]:
        """Build the namespace for resolving string annotations."""
        import sys as _sys
        from typing import Annotated as _Annotated

        from nexusx.context import ExposeAs as _ExposeAs
        from nexusx.context import SendTo as _SendTo

        _module = _sys.modules.get(namespace.get("__module__", ""), None)
        return {
            **(vars(_module) if _module else {}),
            "Annotated": _Annotated,
            "ExposeAs": _ExposeAs,
            "SendTo": _SendTo,
        }

    @staticmethod
    def _build_local_ns(global_ns: dict[str, Any]) -> dict[str, Any]:
        """Build an eval namespace including the caller's locals (for nested class defs).

        Called from __new__, so _getframe(2) reaches the class definition site.
        """
        import sys as _sys

        _frame = _sys._getframe(2)
        return {**global_ns, **_frame.f_locals}

    @staticmethod
    def _merge_overrides(
        field_definitions: dict[str, tuple[Any, Any]],
        override_annotations: dict[str, Any],
        global_ns: dict[str, Any],
        namespace: dict[str, Any],
    ) -> None:
        """Merge ExposeAs/SendTo override annotations from class body in-place."""
        for fname, anno in override_annotations.items():
            if fname not in field_definitions:
                continue
            existing_anno, existing_fi = field_definitions[fname]
            resolved = anno
            if isinstance(resolved, str):
                try:
                    resolved = eval(resolved, global_ns, namespace)  # noqa: S307
                except NameError:
                    continue
            if hasattr(resolved, "__metadata__"):
                for meta in resolved.__metadata__:
                    existing_fi.metadata.append(meta)
                field_definitions[fname] = (resolved, existing_fi)

    @staticmethod
    def _merge_config_overrides(
        field_definitions: dict[str, tuple[Any, Any]],
        subset_info: SubsetConfig,
        local_ns: dict[str, Any],
        namespace: dict[str, Any],
    ) -> None:
        """Merge SubsetConfig expose_as/send_to overrides in-place."""
        from typing import Annotated

        config_overrides = _build_config_overrides(subset_info)

        for fname, synthetic_anno in config_overrides.items():
            if fname not in field_definitions:
                continue
            existing_anno, existing_fi = field_definitions[fname]

            resolved_anno = existing_anno
            if isinstance(resolved_anno, str):
                try:
                    resolved_anno = eval(resolved_anno, local_ns, namespace)  # noqa: S307
                except NameError:
                    continue

            if not isinstance(existing_fi, FieldInfo):
                existing_fi = FieldInfo(default=existing_fi)

            config_metadata = synthetic_anno.__metadata__
            for meta in config_metadata:
                existing_fi.metadata.append(meta)
            wrapped = Annotated[(resolved_anno, *config_metadata)]
            field_definitions[fname] = (wrapped, existing_fi)

    @staticmethod
    def _create_subset_class(
        name: str,
        field_definitions: dict[str, tuple[Any, Any]],
        subset_fields: list[str],
        entity_kls: type[SQLModel],
        namespace: dict,
        auto_excluded: set[str] | None = None,
    ) -> Any:
        """Create the Pydantic model, attach methods and metadata."""
        methods = _extract_methods(namespace)

        create_model_kwargs: dict[str, Any] = {
            "__module__": namespace.get("__module__", __name__),
        }
        config = getattr(entity_kls, "model_config", None)
        if config:
            create_model_kwargs["__config__"] = config

        subset_class = create_model(
            name,
            **field_definitions,
            **create_model_kwargs,
        )

        for method_name, method in methods.items():
            setattr(subset_class, method_name, method)

        setattr(subset_class, SUBSET_REFERENCE, entity_kls)
        _subset_registry[subset_class] = entity_kls
        subset_class.__subset_fields__ = list(subset_fields)
        subset_class.__subset_auto_excluded__ = auto_excluded or set()

        return subset_class


class DefineSubset(metaclass=SubsetMeta):
    """Base class for creating independent DTO models from SQLModel entities.

    Define a subset by specifying the source entity and field names:

        class UserSummary(DefineSubset):
            __subset__ = (User, ('id', 'name'))

    FK fields are automatically hidden from output (exclude=True) but remain
    available internally for relationship resolution.

    Extra fields (resolve_*, post_*) can be declared in the class body.

        class PostSummary(DefineSubset):
            __subset__ = (Post, ('id', 'title', 'author_id'))
            author: UserSummary | None = None

            def post_word_count(self):
                return len(self.title.split())
    """
    pass


# ──────────────────────────────────────────────────────────
# Query builder — select only the columns a DTO needs
# ──────────────────────────────────────────────────────────

def build_dto_select(
    dto_cls: type[BaseModel],
    where: Any | None = None,
):
    """Build a ``select(*columns)`` statement for a DefineSubset DTO.

    Reads the DTO's ``__subset_fields__`` and source entity to produce
    a statement that queries only the scalar columns the DTO needs.
    Relationship field names are filtered out automatically.

    Args:
        dto_cls: A DefineSubset DTO class.
        where: Optional SQLAlchemy where expression
            (e.g. ``Sprint.id == 1``).

    Returns:
        A SQLModel/SQLAlchemy ``Select`` statement.

    Raises:
        ValueError: If *dto_cls* is not a DefineSubset DTO.

    Usage::

        from nexusx import build_dto_select

        stmt = build_dto_select(TaskSummary)
        async with session_factory() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [TaskSummary(**dict(row._mapping)) for row in rows]

    Note:
        When ORM relationships use ``lazy="noload"`` (the recommended
        pattern with ErManager + Resolver), this function provides
        minimal benefit since the only pruning is on scalar columns.
        You can achieve the same result with ``select(Entity)`` and
        ``DTO.model_validate(entity)``.

        Use this function when the DTO selects a small subset of scalar
        columns from a wide table and the column pruning is worthwhile.
    """
    from sqlmodel import select

    entity_cls = get_subset_source(dto_cls)
    if entity_cls is None:
        raise ValueError(
            f"{dto_cls.__name__} is not a DefineSubset DTO "
            f"(no source entity registered)"
        )

    subset_fields = getattr(dto_cls, "__subset_fields__", None)
    if not subset_fields:
        raise ValueError(
            f"{dto_cls.__name__} has no __subset_fields__"
        )

    # Filter out relationship field names and auto-excluded fields —
    # they are not needed in the SELECT statement.
    rel_names = _get_all_relationship_names(entity_cls)
    auto_excluded = getattr(dto_cls, "__subset_auto_excluded__", set())
    column_fields = [
        f for f in subset_fields
        if f not in rel_names and f not in auto_excluded
    ]
    columns = [getattr(entity_cls, f) for f in column_fields]

    stmt = select(*columns)
    if where is not None:
        stmt = stmt.where(where)
    return stmt
