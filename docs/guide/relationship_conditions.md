# Relationship Conditions

FK-derived relationship loading returns every matching row by default. For
"logically only a subset" relationships — soft deletes, archived records,
status filtering — declare the constraint with SQLAlchemy's native join
condition (`primaryjoin` / `secondaryjoin`). nexusx recognizes the extra
conditions and applies them automatically to every loading path of that
relationship (GraphQL nested fields, compose DTO assembly, MCP, federation
member side). No loading code, no nexusx-specific parameters.

## One-to-many / many-to-one: primaryjoin

```python
from typing import Optional
from sqlmodel import Field, Relationship, SQLModel

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str

    comments: list["Comment"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"foreign_keys": "[Comment.owner_id]"},
    )
    # Soft-delete filter: only non-deleted comments
    active_comments: list["Comment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Comment.owner_id]",
            "primaryjoin": "and_(User.id==Comment.owner_id, Comment.status=='active')",
            "viewonly": True,        # optional, see below
            "order_by": "Comment.id",
        },
    )
```

This is exactly the `and_(FK equality, extra condition)` shape you already
use in hand-written join queries. Conditions are per-relationship and
orthogonal: `comments` keeps returning everything, `active_comments` returns
only matching rows.

Many-to-one is the same shape; a non-matching target resolves to `None`
(e.g. an `approver` pointing at a disabled user):

```python
class Comment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")
    approver_id: Optional[int] = Field(default=None, foreign_key="user.id")

    owner: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "Comment.owner_id"}
    )
    approver: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "and_(Comment.approver_id==User.id, User.status=='enabled')",
            "foreign_keys": "Comment.approver_id",
        },
    )
```

## Supported condition forms

| Form | Example |
|------|---------|
| Column vs constant (eq / ne / in, ...) | `Comment.status == 'active'` |
| Null checks (timestamp soft-delete style) | `Comment.deleted_at == None` (compiles to `IS NULL`) |
| Multiple AND conditions | collected independently, all applied |
| `or_` / `not_` combinations | kept whole — OR is never rewritten into AND |
| Enum values | `Comment.visibility == Visibility.public` (lambda form required, see pitfalls) |

## Many-to-many: secondaryjoin

Conditions apply to the **target side** (target-entity columns) or the
**association table's own columns** ("this link row itself is valid"):

```python
class ArticleReader(SQLModel, table=True):
    """Link table (link_model must be the SQLModel class)."""
    article_id: int = Field(foreign_key="article.id", primary_key=True)
    reader_id: int = Field(foreign_key="reader.id", primary_key=True)
    status: str = Field(default="active")

class Article(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    active_readers: list["Reader"] = Relationship(
        link_model=ArticleReader,
        sa_relationship_kwargs={
            "secondaryjoin": lambda: and_(
                Reader.id == ArticleReader.__table__.c.reader_id,
                Reader.status == "active",                      # target column
                ArticleReader.__table__.c.status == "active",   # link-table column
            ),
            "viewonly": True,
        },
    )
```

## Pagination semantics

For relationships with `order_by` (local pagination enabled), the window,
`total_count`, and `has_more` are all computed over the **filtered** set —
`total_count` is the post-filter count, not the unfiltered total. That is
the correct caliber for pagers and progress UIs.

## viewonly is optional

SQLAlchemy allows extra-condition relationships without `viewonly` (no
warning since 2.0), including bidirectional `back_populates`. nexusx only
reads, so `viewonly` makes zero behavioral difference — declaring it is the
recommended way to express read-only write-side semantics, but it is an
SQLAlchemy convention, not a nexusx requirement.

## Unsupported forms (startup-time errors)

These declarations raise `ValueError` when `ErManager` is constructed (at
application startup), with the entity name, relationship name, and offending
column in the message — conditions are never silently dropped, and never
deferred to a runtime SQL error:

- Conditions referencing columns **outside the target entity** (and the
  association table) — e.g. a one-to-many condition on a parent-entity
  column. Loader queries only read the target side; such a condition is
  physically unexecutable.
- Extra conditions on the many-to-many `primaryjoin` (source↔association)
  side — same reason; declare them in `secondaryjoin` instead.
- **Two-column comparisons** other than the FK equality pair.
- Function expressions or subqueries inside conditions.

## Known pitfalls (native SQLAlchemy / SQLModel constraints)

1. `link_model` must be the SQLModel link **class**; a raw `Table` object
   fails during class construction.
2. Annotate relationship fields as `Optional["User"]`; the `"User | None"`
   string annotation combined with `sa_relationship_kwargs` does not resolve.
3. The **string form** of `primaryjoin` / `secondaryjoin` is evaluated with
   only entity class names in scope: enum classes and `Table` objects are
   not visible — use the **lambda** form for those (see the M2M example).
4. Multiple foreign keys to the same target table require SQLAlchemy's
   native `foreign_keys` declaration.

## Relationship to the GraphQL schema

Conditions are query semantics, not schema semantics: SDL and introspection
shapes do not change (field types render as usual) and filtered-empty
results return normally. Under federation, conditions apply on the member
side at load time; the external wire contract is unchanged.
