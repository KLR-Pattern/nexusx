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
**association table's own columns** ("this link row itself is valid"). Either
join side may declare them — the loader routes by the referenced columns, so
a link-table condition works in `primaryjoin` or `secondaryjoin` alike:

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

Two M2M-specific rules:

- Each condition must sit on **one** side only. A single condition mixing
  target and link-table columns (e.g. `or_(Reader.status == "active",
  link.status == "active")`) raises at startup — M2M loading runs separate
  per-table queries and the condition could be applied to neither. Declare
  the two sides as separate conditions (AND) instead.
- Source-entity columns are not readable by the loader on either join side
  and raise at startup.

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
- For many-to-many, a **single condition spanning both** the target and the
  association table (e.g. an `or_` mixing a link column and a target column)
  — the loader runs separate per-table queries; the condition could be
  applied to neither. Split it into separate conditions.
- **Non-equality comparisons** on the FK pair (e.g. `User.id !=
  Comment.owner_id`) — the loader implements the pair as an equality `IN`
  query; rather than silently rewriting your declaration to equality, it
  errors.
- **Two-column comparisons** other than the FK equality pair.
- Function expressions or subqueries inside conditions.

## backref does not propagate conditions to the reverse side

SQLAlchemy's `backref` copies the forward side's conditional `primaryjoin`
to the auto-created reverse relationship. From the reverse side those
conditions reference its *source* entity, which the reverse loader never
reads — so nexusx skips extraction for backref-created relationships (with a
warning) and the reverse keeps plain FK semantics: `comment.br_user`
resolves by FK regardless of conditions, while `user.active_comments`
(where the condition was declared) filters. Declare the reverse explicitly
(with `back_populates` + its own `primaryjoin`) if it must filter too.

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
