"""FromContext marker for UseCaseService method parameters."""


class FromContext:
    """Marker annotation for parameters injected from MCP context_extractor.

    Used with ``Annotated`` to mark method parameters that should receive
    their values from the ``context_extractor`` callback rather than from
    the MCP tool's ``params`` JSON.

    This allows the same UseCaseService method to work seamlessly in both
    FastAPI (where the parameter is passed directly) and MCP (where it is
    extracted from request headers by ``context_extractor``).

    Usage::

        from typing import Annotated
        from nexusx.use_case import UseCaseService, FromContext

        class ProjectService(UseCaseService):
            @classmethod
            async def get_project(
                cls,
                user_id: Annotated[int, FromContext()],
                project_id: int,
            ) -> ProjectDetail:
                ...
    """

    pass


# ──────────────────────────────────────────────────────────
# FromContext detection — the one implementation (spec 026 R6)
# ──────────────────────────────────────────────────────────

from typing import Annotated, Any, get_args, get_origin  # noqa: E402


def is_from_context_annotation(annotation: Any) -> bool:
    """True when ``annotation`` is ``Annotated[T, FromContext(...)]``.

    Shared by the compose schema builder / executor, the REST router and the
    CLI (three private copies before spec 026).
    """
    if get_origin(annotation) is not Annotated:
        return False
    return any(isinstance(meta, FromContext) for meta in get_args(annotation)[1:])


def unwrap_from_context(annotation: Any) -> Any:
    """``Annotated[T, FromContext(...)]`` → ``T``; any other annotation unchanged.

    Only strips the ``Annotated`` shell — a ``list[int]`` parameter stays
    ``list[int]`` (the former CLI helper returned ``int`` for it).
    """
    if get_origin(annotation) is not Annotated:
        return annotation
    args = get_args(annotation)
    return args[0] if args else annotation
