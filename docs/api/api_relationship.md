# Relationships & ER Diagram API

Define custom relationships and generate Mermaid ER diagrams with Relationship and ErDiagram.

## Relationship

Declare custom (non-ORM) relationships between entities.

```python
from nexusx import Relationship

class Task(SQLModel, table=True):
    __relationships__ = [
        Relationship(
            fk="id",
            target=list[Tag],
            name="tags",
            loader=tags_loader,
        )
    ]
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `fk` | `str` | Yes | Field name on the source entity used by DataLoader to collect key values |
| `target` | `type` | Yes | Target type (`Entity` or `list[Entity]`) |
| `name` | `str` | Yes | Relationship name, used for implicit auto-loading matching |
| `loader` | `type` or `callable` | Yes | DataLoader class or async batch function |

### Declaration Location

Declare relationships in the `__relationships__` class attribute of a SQLModel entity class, as a list of `Relationship` instances.

### target Syntax

Choose the appropriate target syntax based on your relationship cardinality:

```python
# Single target (MANYTOONE)
Relationship(fk="owner_id", target=User, name="owner", loader=user_loader)

# List target (ONETOMANY)
Relationship(fk="id", target=list[Tag], name="tags", loader=tags_loader)
```

!!! tip
    Use `target=Entity` for many-to-one relationships (like "a task has one owner") and `target=list[Entity]` for one-to-many relationships (like "a sprint has many tasks"). This syntax matches the expected return type of your DataLoader.

!!! tip
    The `name` parameter enables implicit auto-loading — when you declare a field with the same name as a relationship, Resolver automatically loads it without requiring a `resolve_*` method. Keep your relationship names consistent with your DTO field names for clean, declarative code.

## ErDiagram

Generate Mermaid ER diagrams from your entity relationships.

```python
from nexusx import ErDiagram

diagram = ErDiagram.from_sqlmodel([Sprint, Task, User])
print(diagram.to_mermaid())
```

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `from_sqlmodel(entities)` | `-> ErDiagram` | Build from SQLModel entity classes |
| `from_er_manager(er_manager)` | `-> ErDiagram` | Build from an ErManager, including virtual entities |
| `to_mermaid()` | `-> str` | Generate a Mermaid ER diagram string |

Structured entity and relationship metadata is available through
`diagram.entities`. Registry-level classes and relationships remain available
from `er.get_all_entities()` and `er.get_all_relationships()`.

### Mermaid Output Example

```mermaid
erDiagram
    Sprint ||--o{ Task : "has many"
    Task }o--|| User : "owner"
```

### From ErManager

Extract the diagram from an existing ErManager:

```python
er = ErManager(base=SQLModel, session_factory=async_session)
diagram = ErDiagram.from_er_manager(er)
print(diagram.to_mermaid())
```
