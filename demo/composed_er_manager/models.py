"""ComposedErManager demo models: blog + shop in two separate engines.

The cross-engine edge ``CmUser.orders → CmOrder`` is deliberately NOT declared
on the entity — it lives on the ComposedErManager (``cross_relationships=`` in
``app.py``), so each member ErManager stays self-contained (specs/019 DD-02).
"""

from typing import Optional

from sqlmodel import Field, Relationship, SQLModel, select

from nexusx import query


class CmBlogBase(SQLModel):
    """Base for the blog-engine entities (own tables, own DB file)."""

    pass


class CmShopBase(SQLModel):
    """Base for the shop-engine entities (own tables, own DB file)."""

    pass


class CmUser(CmBlogBase, table=True):
    __tablename__ = "cm_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str

    posts: list["CmPost"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"order_by": "CmPost.id"},
    )
    # NOTE: no `orders` field here — that cross-engine edge is declared on the
    # ComposedErManager (see app.py), keeping this member self-contained.

    @query
    async def get_users(cls, limit: int = 10) -> list["CmUser"]:
        """List users (blog engine)."""
        from .database import get_blog_session

        async with get_blog_session() as s:
            return list((await s.exec(select(cls).limit(limit))).all())


class CmPost(CmBlogBase, table=True):
    __tablename__ = "cm_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    content: str
    author_id: int = Field(foreign_key="cm_user.id")

    author: Optional["CmUser"] = Relationship(back_populates="posts")


class CmOrder(CmShopBase, table=True):
    __tablename__ = "cm_order"

    id: int | None = Field(default=None, primary_key=True)
    # Cross-engine logical FK → cm_user.id; deliberately no SQL FK, since the
    # two tables live in different SQLite files.
    user_id: int
    total: float

    items: list["CmOrderItem"] = Relationship(
        back_populates="order",
        sa_relationship_kwargs={"order_by": "CmOrderItem.id"},
    )

    @query
    async def get_orders(cls, limit: int = 10) -> list["CmOrder"]:
        """List orders (shop engine)."""
        from .database import get_shop_session

        async with get_shop_session() as s:
            return list((await s.exec(select(cls).limit(limit))).all())


class CmOrderItem(CmShopBase, table=True):
    __tablename__ = "cm_order_item"

    id: int | None = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="cm_order.id")
    qty: int

    order: Optional["CmOrder"] = Relationship(back_populates="items")
