"""Decorators for marking SQLModel methods as GraphQL queries and mutations."""

from __future__ import annotations

from collections.abc import Callable


def query(func: Callable) -> classmethod:
    """Mark a method as a GraphQL query.

    This decorator automatically converts the method to a classmethod.
    The method name is used **verbatim** as the GraphQL field name (no
    camelCase, no entity prefix); the field lives on the entity's
    ``{Entity}Query`` group type, which the root ``Query`` mounts as one
    field per entity. The description is taken from the method's docstring.

    Args:
        func: The method to decorate.

    Returns:
        A classmethod decorator.

    Example:
        ```python
        from sqlmodel import SQLModel
        from nexusx import query

        class User(SQLModel, table=True):
            id: int
            name: str

            @query
            async def get_all(cls, limit: int = 10) -> list['User']:
                \"\"\"Get all users with optional limit.\"\"\"
                return await fetch_users(limit)

            @query
            async def get_by_id(cls, id: int) -> Optional['User']:
                \"\"\"Get a user by ID.\"\"\"
                return await fetch_user(id)
        ```

    This generates the following GraphQL Schema:
        ```graphql
        type UserQuery {
            \"\"\"Get all users with optional limit.\"\"\"
            get_all(limit: Int): [User!]!
            \"\"\"Get a user by ID.\"\"\"
            get_by_id(id: Int!): User
        }

        type Query {
            User: UserQuery!
        }
        ```
    """
    func._graphql_query = True  # type: ignore[attr-defined]
    func._graphql_query_description = (func.__doc__.strip() if func.__doc__ else "")  # type: ignore[attr-defined]
    return classmethod(func)


def mutation(func: Callable) -> classmethod:
    """Mark a method as a GraphQL mutation.

    This decorator automatically converts the method to a classmethod.
    The method name is used **verbatim** as the GraphQL field name (no
    camelCase, no entity prefix); the field lives on the entity's
    ``{Entity}Mutation`` group type, which the root ``Mutation`` mounts as
    one field per entity. The description is taken from the method's docstring.

    Args:
        func: The method to decorate.

    Returns:
        A classmethod decorator.

    Example:
        ```python
        from sqlmodel import SQLModel
        from nexusx import mutation

        class User(SQLModel, table=True):
            id: int
            name: str
            email: str

            @mutation
            async def create(cls, name: str, email: str) -> 'User':
                \"\"\"Create a new user.\"\"\"
                return await create_user(name, email)

            @mutation
            async def update_email(cls, id: int, email: str) -> 'User':
                \"\"\"Update user's email.\"\"\"
                return await update_user_email(id, email)
        ```

    This generates the following GraphQL Schema:
        ```graphql
        type UserMutation {
            \"\"\"Create a new user.\"\"\"
            create(name: String!, email: String!): User!
            \"\"\"Update user's email.\"\"\"
            update_email(id: Int!, email: String!): User!
        }

        type Mutation {
            User: UserMutation!
        }
        ```
    """
    func._graphql_mutation = True  # type: ignore[attr-defined]
    func._graphql_mutation_description = (func.__doc__.strip() if func.__doc__ else "")  # type: ignore[attr-defined]
    return classmethod(func)
