"""ER Diagram — visualize and document SQLModel entity relationships.

Generates Mermaid ER diagrams from SQLModel ORM metadata.
Uses the same relationship discovery logic as LoaderRegistry.

Usage:
    from nexusx import ErDiagram

    diagram = ErDiagram.from_sqlmodel(entities=[User, Post, Comment])
    print(diagram.to_mermaid())

    # Entity details
    for entity_info in diagram.entities:
        print(f"{entity_info.name}: {[r.name for r in entity_info.relationships]}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import RelationshipProperty
from sqlmodel import SQLModel

from nexusx.relationship import is_virtual_entity


class RelationType(str, Enum):
    MANYTOONE = "MANYTOONE"
    ONETOMANY = "ONETOMANY"
    MANYTOMANY = "MANYTOMANY"


@dataclass
class RelationInfo:
    """A single relationship between two entities."""
    name: str  # relationship field name
    source: str  # source entity name
    target: str  # target entity name
    fk_field: str  # FK field name on source side
    relation_type: RelationType


@dataclass
class EntityInfo:
    """An entity with its fields and relationships."""
    name: str
    table_name: str
    fields: list[str]
    fk_fields: list[str]
    relationships: list[RelationInfo] = field(default_factory=list)
    is_virtual: bool = False


@dataclass
class ErDiagram:
    """ER Diagram constructed from SQLModel entity metadata.

    Create via ErDiagram.from_sqlmodel() and visualize via to_mermaid().
    """

    entities: list[EntityInfo]

    @classmethod
    def from_sqlmodel(cls, entities: list[type[SQLModel]]) -> ErDiagram:
        """Build an ER Diagram from SQLModel entity classes.

        Inspects SQLAlchemy ORM metadata to discover relationships,
        field names, and foreign keys.

        Args:
            entities: List of SQLModel entity classes (with table=True).
                Every entry MUST be a SQLModel subclass. For projects that
                mix SQLModel entities with plain BaseModel virtual roots
                (registered via ``ErManager.add_virtual_entities()``), use
                ``ErDiagram.from_er_manager(er)`` instead — it reads from
                the ErManager registry and handles both uniformly.

        Raises:
            TypeError: If any entry is not a SQLModel subclass. Pre-feature
                code that passed BaseModel classes here would crash later
                inside ``sa_inspect()`` with ``NoInspectionAvailable`` —
                the guard catches the mismatch up front.

        Returns:
            ErDiagram with entity and relationship information.
        """
        for entity in entities:
            if not (isinstance(entity, type) and issubclass(entity, SQLModel)):
                raise TypeError(
                    f"ErDiagram.from_sqlmodel() accepts only SQLModel classes; "
                    f"got {entity!r}. For mixed SQLModel + BaseModel entity "
                    f"sets, use ErDiagram.from_er_manager(er)."
                )
        return cls._build([e for e in entities], sqlmodel_only=True)

    @classmethod
    def from_er_manager(cls, er_manager: Any) -> ErDiagram:
        """Build an ErDiagram from an ErManager's registry.

        Includes both SQLModel entities (registered via ``__init__``'s
        ``base=`` / ``entities=``) and plain BaseModel virtual entities
        (registered via ``add_virtual_entities()``). Virtual entities
        appear with their ``model_fields`` schema but no table name and
        no foreign keys.

        Args:
            er_manager: An ErManager instance.

        Returns:
            ErDiagram with both SQLModel and virtual entity information.
        """
        all_entities = er_manager.get_all_entities()
        all_relationships = er_manager.get_all_relationships()
        return cls._build(
            all_entities,
            sqlmodel_only=False,
            registry_relationships=all_relationships,
        )

    @classmethod
    def _build(
        cls,
        entities: list[type],
        *,
        sqlmodel_only: bool,
        registry_relationships: dict[type, dict[str, Any]] | None = None,
    ) -> ErDiagram:
        """Shared build path for from_sqlmodel / from_er_manager.

        Args:
            entities: Entity classes (SQLModel and optionally BaseModel).
            sqlmodel_only: If True, every entity must be SQLModel and the
                SQLAlchemy-inspection path is used for relationships. If
                False, BaseModel entities are handled via __relationships__
                only (no sa_inspect on them).
            registry_relationships: When provided (from_er_manager path),
                use these pre-computed RelationshipInfo entries instead of
                re-discovering them. This is the source of truth for both
                SQLModel and virtual entities in the registry.
        """
        from nexusx.relationship import get_custom_relationships

        entity_map: dict[type, EntityInfo] = {}
        entity_set = set(entities)

        # First pass: collect entity info
        for entity in entities:
            is_sqlmodel = isinstance(entity, type) and issubclass(entity, SQLModel)
            if is_sqlmodel:
                mapper = sa_inspect(entity)
                table_name = getattr(entity, "__tablename__", entity.__name__.lower())
            else:
                mapper = None
                # Virtual entity — no table. Use the class name as the
                # label; table_name stays empty to signal "no table".
                table_name = ""

            # Collect field names, separating FK fields
            all_fields = []
            fk_fields = []
            for fname, finfo in entity.model_fields.items():
                all_fields.append(fname)
                if _is_fk_field(finfo):
                    fk_fields.append(fname)

            # Remove relationship names from field list (SQLModel ORM rels only)
            rel_names: set[str] = set()
            if mapper and hasattr(mapper, "relationships"):
                rel_names = {r.key for r in mapper.relationships}
            # Also exclude __relationships__ field names from the scalar list
            for crel in get_custom_relationships(entity):
                rel_names.add(crel.name)

            scalar_fields = [f for f in all_fields if f not in rel_names]

            entity_info = EntityInfo(
                name=entity.__name__,
                table_name=table_name,
                fields=scalar_fields,
                fk_fields=fk_fields,
                is_virtual=is_virtual_entity(entity),
            )
            entity_map[entity] = entity_info

        # Second pass: SQLModel ORM relationships (only for SQLModel entities).
        # Skip entirely in the from_er_manager path — registry_relationships
        # is the source of truth there.
        if registry_relationships is None:
            for entity in entities:
                if not (isinstance(entity, type) and issubclass(entity, SQLModel)):
                    continue
                mapper = sa_inspect(entity)
                if not mapper or not hasattr(mapper, "relationships"):
                    continue

                for rel in mapper.relationships:
                    target_entity = rel.mapper.class_
                    if target_entity not in entity_set:
                        continue

                    direction = _get_relation_direction(rel)
                    fk_field = ""
                    if rel.local_columns:
                        fk_field = list(rel.local_columns)[0].name

                    entity_map[entity].relationships.append(
                        RelationInfo(
                            name=rel.key,
                            source=entity.__name__,
                            target=target_entity.__name__,
                            fk_field=fk_field,
                            relation_type=direction,
                        )
                    )

        # Third pass: custom relationships from __relationships__.
        # Used directly when registry_relationships is None (from_sqlmodel
        # path). For from_er_manager, registry_relationships provides
        # RelationshipInfo entries uniformly across SQLModel + BaseModel.
        if registry_relationships is None:
            for entity in entities:
                for crel in get_custom_relationships(entity):
                    if crel.target_entity not in entity_set:
                        continue
                    direction = (
                        RelationType.ONETOMANY if crel.is_list else RelationType.MANYTOONE
                    )
                    entity_map[entity].relationships.append(
                        RelationInfo(
                            name=crel.name,
                            source=entity.__name__,
                            target=crel.target_entity.__name__,
                            fk_field=crel.fk,
                            relation_type=direction,
                        )
                    )
        else:
            # from_er_manager path — registry is the source of truth.
            for entity, rels in registry_relationships.items():
                if entity not in entity_map:
                    continue
                for rel_name, rel_info in rels.items():
                    target = rel_info.target_entity
                    if target not in entity_set:
                        continue
                    direction = (
                        RelationType.ONETOMANY if rel_info.is_list else RelationType.MANYTOONE
                    )
                    entity_map[entity].relationships.append(
                        RelationInfo(
                            name=rel_name,
                            source=entity.__name__,
                            target=target.__name__,
                            fk_field=rel_info.fk_field,
                            relation_type=direction,
                        )
                    )

        return cls(entities=list(entity_map.values()))

    def to_mermaid(self) -> str:
        """Generate a Mermaid ER diagram string.

        Returns:
            Mermaid erDiagram syntax string.
        """
        lines = ["erDiagram"]

        # Entity definitions
        for entity in self.entities:
            lines.append(f"    {entity.name} {{")
            for fname in entity.fields:
                lines.append(f"        {fname}")
            lines.append("    }")

        # Relationships
        seen_rels: set[tuple[str, str]] = set()
        for entity in self.entities:
            for rel in entity.relationships:
                # Avoid duplicate relationship lines
                pair = tuple(sorted([rel.source, rel.target]))
                rel_key = (pair, rel.name)
                if rel_key in seen_rels:
                    continue
                seen_rels.add(rel_key)

                if rel.relation_type == RelationType.ONETOMANY:
                    lines.append(
                        f"    {rel.source} ||--o{{ {rel.target} : {rel.name}"
                    )
                elif rel.relation_type == RelationType.MANYTOONE:
                    lines.append(
                        f"    {rel.target} ||--o{{ {rel.source} : {rel.name}"
                    )
                elif rel.relation_type == RelationType.MANYTOMANY:
                    lines.append(
                        f"    {rel.source} }}o--o{{ {rel.target} : {rel.name}"
                    )

        return "\n".join(lines)


def _is_fk_field(field_info: Any) -> bool:
    """Check if a FieldInfo represents a foreign key field."""
    if hasattr(field_info, "foreign_key") and isinstance(field_info.foreign_key, str):
        return True
    if hasattr(field_info, "metadata"):
        for meta in field_info.metadata:
            if hasattr(meta, "foreign_key") and isinstance(meta.foreign_key, str):
                return True
    return False


def _get_relation_direction(rel: RelationshipProperty) -> RelationType:
    """Determine the direction of a SQLAlchemy relationship."""
    if rel.direction.name == "MANYTOONE":
        return RelationType.MANYTOONE
    elif rel.direction.name == "ONETOMANY":
        return RelationType.ONETOMANY
    else:
        return RelationType.MANYTOMANY
