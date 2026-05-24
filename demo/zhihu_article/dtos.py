"""DefineSubset DTOs for the order system demo.

Shows progressive complexity:
- Basic field selection + FK hiding (CustomerDTO, ProductDTO)
- Relationship fields with implicit auto-loading (OrderItemDTO, OrderDTO)
- Derived fields via post_* (subtotal, item_count)
- Custom relationship auto-loading (ProductReviewDTO)
"""

from nexusx import DefineSubset, SubsetConfig

from demo.zhihu_article.models import Customer, Order, OrderItem, Product, Review


class CustomerDTO(DefineSubset):
    """Customer DTO with selected fields."""
    __subset__ = SubsetConfig(kls=Customer, fields=['id', 'name', 'tier'])


class ProductDTO(DefineSubset):
    """Product DTO — basic field selection."""
    __subset__ = SubsetConfig(kls=Product, fields=['id', 'name', 'price'])


class ProductReviewDTO(DefineSubset):
    """Review DTO — loaded via custom Relationship, not ORM."""
    __subset__ = SubsetConfig(kls=Review, fields=['id', 'rating', 'comment', 'reviewer_name'])


class ProductWithReviewsDTO(DefineSubset):
    """Product DTO with reviews loaded via custom Relationship.

    The 'reviews' field name matches the custom relationship defined in
    Product.__relationships__. Resolver auto-loads it without needing
    a resolve_* method.
    """
    __subset__ = SubsetConfig(kls=Product, fields=['id', 'name', 'price'])

    reviews: list[ProductReviewDTO] = []
    review_count: int = 0
    avg_rating: float = 0.0

    def post_review_count(self):
        return len(self.reviews)

    def post_avg_rating(self):
        if not self.reviews:
            return 0.0
        return round(sum(r.rating for r in self.reviews) / len(self.reviews), 1)


class OrderItemDTO(DefineSubset):
    """Order item DTO with auto-loaded product and derived subtotal.

    - product: implicit auto-load (matches OrderItem.product relationship)
    - subtotal: derived field computed after product is loaded
    - product_id is needed for auto-loading but hidden from output
    """
    __subset__ = SubsetConfig(kls=OrderItem, fields=['quantity', 'unit_price', 'product_id'])

    product: ProductDTO | None = None
    subtotal: float = 0.0

    def post_subtotal(self):
        return round(self.quantity * self.unit_price, 2)


class OrderDTO(DefineSubset):
    """Order DTO with customer, items, and derived item_count.

    - customer: implicit auto-load (matches Order.customer relationship)
    - items: implicit auto-load (matches Order.items relationship)
    - item_count: derived from loaded items
    - customer_id is needed for auto-loading but hidden from output
    """
    __subset__ = SubsetConfig(kls=Order, fields=['id', 'status', 'total_amount', 'created_at', 'customer_id'])

    customer: CustomerDTO | None = None
    items: list[OrderItemDTO] = []
    item_count: int = 0

    def post_item_count(self):
        return len(self.items)
