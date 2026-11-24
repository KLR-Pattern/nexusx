"""Naming conversion utilities.

The one home for case conversions (spec 026 R4 / R5): ``pascal_case`` serves
the synthetic GraphQL enum / package names (``standard_queries`` and
``utils.pagination_schema`` used to keep a copy each), ``snake_case`` serves
the UseCase URL segment and CLI command names (``use_case.router`` and
``use_case.cli`` used to keep a copy each).
"""

from __future__ import annotations

import re
import warnings

_CAMEL_TO_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def pascal_case(value: str) -> str:
    """``snake_case`` → ``PascalCase`` (``user_id`` → ``UserId``)."""
    return "".join(part[:1].upper() + part[1:] for part in value.split("_") if part)


def snake_case(name: str) -> str:
    """``PascalCase`` / ``camelCase`` → ``snake_case`` (``UserService`` → ``user_service``)."""
    return _CAMEL_TO_SNAKE_RE.sub("_", name).lower()


def to_camel_case(name: str) -> str:
    """Convert snake_case to camelCase.

    .. deprecated::
        GraphQL field names are the verbatim method names since the grouped
        layout (no camelCase anywhere), so nothing in nexusx calls this.
        Scheduled for removal in 8.0 (issue #160 M4).

    Examples:
        >>> to_camel_case("get_all")
        'getAll'
    """
    warnings.warn(
        "nexusx.utils.naming.to_camel_case is deprecated (unused since the "
        "grouped schema layout) and will be removed in 8.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])
