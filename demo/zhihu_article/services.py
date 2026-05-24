"""UseCaseService business services for the order system demo.

These services define business operations that become MCP-callable tools
via create_use_case_mcp_server. The same code also powers FastAPI routes.

Each method:
1. Uses build_dto_select() for optimized SQL (only needed columns)
2. Uses Resolver to auto-load relationships and compute derived fields
3. Returns DTOs (Pydantic models) that serialize cleanly to JSON
"""

from nexusx import UseCaseService, build_dto_select, query, mutation

from demo.zhihu_article.database import async_session
from demo.zhihu_article.dtos import CustomerDTO, OrderDTO, ProductWithReviewsDTO
from demo.zhihu_article.models import Customer, Order, Product


# Resolver is created by ErManager in mcp_server.py and injected here.
# This avoids circular imports while keeping services testable.
_Resolver = None


def set_resolver(resolver_cls):
    global _Resolver
    _Resolver = resolver_cls


class OrderService(UseCaseService):
    """Order management — query and manage orders."""

    @query
    async def get_orders(cls, status: str = "", limit: int = 10) -> list[OrderDTO]:
        """Get orders, optionally filtered by status.

        Args:
            status: Filter by order status (pending/shipped/cancelled). Empty = all.
            limit: Maximum number of orders to return.
        """
        stmt = build_dto_select(OrderDTO)
        if status:
            stmt = stmt.where(Order.status == status).limit(limit)
        else:
            stmt = stmt.limit(limit)

        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [OrderDTO(**dict(row._mapping)) for row in rows]
        return await _Resolver().resolve(dtos)

    @query
    async def get_order_detail(cls, order_id: int) -> OrderDTO | None:
        """Get a single order with full details (customer + items + products).

        Args:
            order_id: The order ID to look up.
        """
        stmt = build_dto_select(OrderDTO, where=Order.id == order_id)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        if not rows:
            return None
        dto = OrderDTO(**dict(rows[0]._mapping))
        return await _Resolver().resolve(dto)

    @mutation
    async def cancel_order(cls, order_id: int) -> OrderDTO | None:
        """Cancel an order by ID.

        Args:
            order_id: The order ID to cancel.
        """
        async with async_session() as session:
            order = await session.get(Order, order_id)
            if not order:
                return None
            order.status = "cancelled"
            session.add(order)
            await session.commit()
            await session.refresh(order)

        dto = OrderDTO(
            id=order.id,
            status=order.status,
            total_amount=order.total_amount,
            created_at=order.created_at,
        )
        return await _Resolver().resolve(dto)


class CustomerService(UseCaseService):
    """Customer management — query customers and their order history."""

    @query
    async def get_customers(cls, tier: str = "") -> list[CustomerDTO]:
        """Get customers, optionally filtered by tier.

        Args:
            tier: Filter by customer tier (regular/silver/gold/platinum). Empty = all.
        """
        stmt = build_dto_select(CustomerDTO)
        if tier:
            stmt = stmt.where(Customer.tier == tier)

        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        return [CustomerDTO(**dict(row._mapping)) for row in rows]

    @query
    async def get_customer_history(cls, customer_id: int, limit: int = 5) -> list[OrderDTO]:
        """Get a customer's recent orders with full details.

        Args:
            customer_id: The customer ID.
            limit: Maximum number of orders to return.
        """
        stmt = build_dto_select(OrderDTO, where=Order.customer_id == customer_id).limit(limit)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [OrderDTO(**dict(row._mapping)) for row in rows]
        return await _Resolver().resolve(dtos)


class ProductService(UseCaseService):
    """Product management — query products with review data."""

    @query
    async def get_products(cls, category: str = "") -> list[ProductWithReviewsDTO]:
        """Get products with reviews loaded via custom Relationship.

        Args:
            category: Filter by product category. Empty = all.
        """
        stmt = build_dto_select(ProductWithReviewsDTO)
        if category:
            stmt = stmt.where(Product.category == category)

        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [ProductWithReviewsDTO(**dict(row._mapping)) for row in rows]
        return await _Resolver().resolve(dtos)
