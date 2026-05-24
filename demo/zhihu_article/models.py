"""SQLModel entities for the order system demo.

Entity relationship graph:

    Customer ──1:N──→ Order ──1:N──→ OrderItem ──N:1──→ Product
                                                  │
                                            (custom Relationship)
                                                  ↓
                                               Review

ORM relationships:
    - Customer → Order (ONETOMANY)
    - Order → OrderItem (ONETOMANY)
    - OrderItem → Product (MANYTOONE)

Custom relationship (non-ORM):
    - Product → Review via __relationships__ (simulates external data source)
"""

from collections import defaultdict
from typing import Optional

from sqlmodel import Field, Relationship as SQLRelationship, SQLModel, select

from nexusx import Relationship


class Customer(SQLModel, table=True):
    __tablename__ = "zh_customer"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str
    tier: str = "regular"  # regular / silver / gold / platinum

    orders: list["Order"] = SQLRelationship(back_populates="customer")


class Review(SQLModel, table=True):
    """Review entity — simulates data from an external review service.

    Though stored in the same DB for the demo, the Product → Review
    relationship is deliberately NOT an ORM relationship. It uses a
    custom __relationships__ entry with a hand-written async loader,
    demonstrating how nexusx handles cross-service data.
    """

    __tablename__ = "zh_review"

    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    rating: int  # 1-5
    comment: str
    reviewer_name: str


# ── Custom loader for Product → Review (non-ORM relationship) ──


async def _reviews_by_product_id_loader(product_ids: list[int]) -> list[list[Review]]:
    """Load reviews for multiple products in a single batch.

    This simulates calling an external review service:
        GET /api/reviews?product_ids=1,2,3

    In production this would be an HTTP call to a review microservice,
    or a query against a separate database. For the demo, it queries
    the same SQLite database.
    """
    from demo.zhihu_article.database import async_session

    async with async_session() as session:
        rows = (await session.exec(select(Review).where(Review.product_id.in_(product_ids)))).all()

    grouped: dict[int, list[Review]] = defaultdict(list)
    for r in rows:
        grouped[r.product_id].append(r)

    return [grouped.get(pid, []) for pid in product_ids]


class Product(SQLModel, table=True):
    __tablename__ = "zh_product"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    price: float
    category: str

    order_items: list["OrderItem"] = SQLRelationship(back_populates="product")

    # Custom non-ORM relationship: simulates loading reviews from an external service.
    __relationships__ = [
        Relationship(
            fk="id",
            target=list[Review],
            name="reviews",
            loader=_reviews_by_product_id_loader,
            description="Product reviews (custom loader, simulates external service)",
        )
    ]


class Order(SQLModel, table=True):
    __tablename__ = "zh_order"

    id: int | None = Field(default=None, primary_key=True)
    status: str = "pending"  # pending / shipped / cancelled
    total_amount: float = 0.0
    created_at: str = ""

    customer_id: int = Field(foreign_key="zh_customer.id")

    customer: Optional["Customer"] = SQLRelationship(back_populates="orders")
    items: list["OrderItem"] = SQLRelationship(
        back_populates="order",
        sa_relationship_kwargs={"order_by": "OrderItem.id"},
    )


class OrderItem(SQLModel, table=True):
    __tablename__ = "zh_order_item"

    id: int | None = Field(default=None, primary_key=True)
    quantity: int
    unit_price: float

    order_id: int = Field(foreign_key="zh_order.id")
    product_id: int = Field(foreign_key="zh_product.id")

    order: Optional["Order"] = SQLRelationship(back_populates="items")
    product: Optional["Product"] = SQLRelationship(back_populates="order_items")
