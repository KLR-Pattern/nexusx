"""Test standard queries in demo."""

from demo.blog.database import async_session
from demo.blog.models import BaseEntity
from nexusx import AutoQueryConfig, GraphQLHandler

config = AutoQueryConfig(
    default_limit=20,
)

handler = GraphQLHandler(base=BaseEntity, session_factory=async_session, auto_query_config=config)

sdl = handler.get_sdl()

print("=== Demo with Standard Queries ===\n")
print(sdl)

# Check if standard queries exist (grouped by entity at the GraphQL root)
assert "User: UserQuery!" in sdl
assert "Post: PostQuery!" in sdl
assert "Comment: CommentQuery!" in sdl
assert "type UserQuery {" in sdl
assert "type PostQuery {" in sdl
assert "type CommentQuery {" in sdl
assert "by_id(id: Int!): User" in sdl
assert "by_filter(filter: UserFilterInput, limit: Int): [User!]!" in sdl
assert "by_id(id: Int!): Post" in sdl
assert "by_filter(filter: PostFilterInput, limit: Int): [Post!]!" in sdl
assert "by_id(id: Int!): Comment" in sdl
assert "by_filter(filter: CommentFilterInput, limit: Int): [Comment!]!" in sdl

print("\n✅ All standard queries added successfully!")
