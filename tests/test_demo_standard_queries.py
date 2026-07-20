"""Test standard queries with the demo models."""

from __future__ import annotations

from demo.blog.database import async_session

# Import demo models
from demo.blog.models import BaseEntity, Comment, Post, User
from nexusx import AutoQueryConfig, GraphQLHandler, add_standard_queries


def test_demo_with_standard_queries():
    """Test adding standard queries to demo models."""
    # Add standard queries to all demo entities
    config = AutoQueryConfig(
        default_limit=20,
    )
    add_standard_queries([User, Post, Comment], config, async_session)

    # Verify methods exist
    assert hasattr(User, "by_id")
    assert hasattr(User, "by_filter")
    assert hasattr(Post, "by_id")
    assert hasattr(Post, "by_filter")
    assert hasattr(Comment, "by_id")
    assert hasattr(Comment, "by_filter")

    # Generate SDL
    handler = GraphQLHandler(
        base=BaseEntity, session_factory=async_session, auto_query_config=config
    )
    sdl = handler.get_sdl()

    print("=== Generated SDL with Standard Queries ===\n")
    print(sdl)
    print("\n=== End of SDL ===\n")

    # Verify SDL contains expected queries (grouped by entity at the GraphQL root)
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

    # Verify filter input types
    assert "input UserFilterInput" in sdl
    assert "input PostFilterInput" in sdl
    assert "input CommentFilterInput" in sdl

    print("✅ All standard queries are successfully added to demo models!")


def test_graphql_handler_with_auto_config():
    """Test using auto_query_config directly in GraphQLHandler."""
    config = AutoQueryConfig(
        default_limit=20,
    )

    handler = GraphQLHandler(
        base=BaseEntity, session_factory=async_session, auto_query_config=config
    )
    sdl = handler.get_sdl()

    # Verify SDL contains expected queries (grouped by entity at the GraphQL root)
    assert "User: UserQuery!" in sdl
    assert "type UserQuery {" in sdl
    assert "by_id(id: Int!): User" in sdl
    assert "by_filter(filter: UserFilterInput, limit: Int): [User!]!" in sdl

    print("✅ auto_query_config works with GraphQLHandler!")


if __name__ == "__main__":
    test_demo_with_standard_queries()
    print()
    test_graphql_handler_with_auto_config()
    print()
    print("🎉 All tests passed!")
