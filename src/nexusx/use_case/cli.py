"""CLI generator for UseCaseService via Typer.

Provides ``create_use_case_cli()`` to create a Typer app that exposes
UseCaseService methods as CLI commands. Each service becomes a command
group, each method a command within that group.

Usage::

    from nexusx import UseCaseAppConfig, create_use_case_cli

    cli = create_use_case_cli(UseCaseAppConfig(
        name="project",
        services=[UserService, TaskService],
    ))
    # Invoke: python -m myapp user-service list-users
    cli()
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import TYPE_CHECKING, Any, get_args, get_origin, get_type_hints

if TYPE_CHECKING:
    import typer

    from nexusx.use_case.types import UseCaseAppConfig

from nexusx.core_builder import SelectionError
from nexusx.use_case.business import USE_CASE_METHODS_ATTR
from nexusx.use_case.selection import apply_selection
from nexusx.use_case.serialization import serialize_result as _serialize_result

_CAMEL_TO_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake(name: str) -> str:
    return _CAMEL_TO_SNAKE_RE.sub("_", name).lower()


def _unwrap_from_context(annotation: Any) -> Any:
    """Extract the inner type from Annotated[T, FromContext()]."""

    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        return args[0] if args else annotation
    return annotation


def _param_help(name: str, annotation: Any) -> str:
    """Build a help string for a CLI param; prefer a str in Annotated metadata."""
    import typing

    if get_origin(annotation) is typing.Annotated:
        for meta in get_args(annotation)[1:]:
            if isinstance(meta, str):
                return meta
    return name


def _format_return_help(return_annotation: Any) -> str | None:
    """Format the return DTO's top-level fields so users know what --select can pick."""
    from nexusx.use_case.selection import _get_pydantic_core_type

    model = _get_pydantic_core_type(return_annotation)
    if model is None:
        return None
    lines = [f"Returns {model.__name__}:"]
    for fname, finfo in model.model_fields.items():
        nested = _get_pydantic_core_type(finfo.annotation)
        type_name = getattr(finfo.annotation, "__name__", str(finfo.annotation))
        marker = "  (nested, selectable)" if nested is not None else ""
        lines.append(f"  {fname}: {type_name}{marker}")
    return "\n".join(lines)


def _build_command(
    service_cls: type,
    method_name: str,
    method: Any,
    description: str,
) -> Any:
    """Create an async command function for a single use case method."""
    func = method.__func__ if isinstance(method, classmethod) else method

    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        hints = {}

    sig = inspect.signature(func)
    return_annotation = hints.get("return", sig.return_annotation)

    # Build parameter info, mapping FromContext to plain params
    param_infos: list[tuple[str, Any, Any, str]] = []  # (name, type, default, help)
    for name, param in sig.parameters.items():
        if name == "cls":
            continue
        anno = hints.get(name, param.annotation)
        if anno is inspect.Parameter.empty:
            anno = str
        help_text = _param_help(name, anno)  # before unwrap, while Annotated is visible
        anno = _unwrap_from_context(anno)
        default = param.default if param.default is not inspect.Parameter.empty else ...
        param_infos.append((name, anno, default, help_text))

    def _command(**kwargs: Any) -> None:
        # asyncio.run creates a new loop — cannot be called inside an existing loop
        select = kwargs.pop("select", None)
        result = asyncio.run(method(**kwargs))
        if select:
            try:
                result = apply_selection(result, return_annotation, select)
            except SelectionError as e:
                typer.echo(
                    f"selection error: {e}\n"
                    'expected "name" or "id tasks { title }"',
                    err=True,
                )
                raise typer.Exit(1) from None
        print(json.dumps(_serialize_result(result), indent=2, ensure_ascii=False))

    # Set signature for Typer to introspect — use typer.Option so all params
    # become CLI options (--param-name) instead of positional arguments.
    import typer

    params = []
    for pname, panno, pdefault, help_text in param_infos:
        default = typer.Option(pdefault, help=help_text)
        params.append(
            inspect.Parameter(
                pname, inspect.Parameter.KEYWORD_ONLY,
                default=default, annotation=panno,
            )
        )
    # --select: GraphQL-like field projection (reuses the MCP selection engine).
    params.append(
        inspect.Parameter(
            "select",
            inspect.Parameter.KEYWORD_ONLY,
            default=typer.Option(
                None,
                "--select",
                help='GraphQL-like field projection, e.g. "name" or "id tasks { title }"',
            ),
            annotation=str,
        )
    )
    _command.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    doc = description or method_name
    return_help = _format_return_help(return_annotation)
    if return_help:
        doc = f"{doc}\n\n{return_help}"
    _command.__doc__ = doc
    _command.__name__ = method_name

    return _command


def create_use_case_cli(
    config: UseCaseAppConfig,
    app_name: str | None = None,
) -> typer.Typer:
    """Create a Typer CLI app from UseCaseAppConfig.

    Each UseCaseService becomes a command group (subcommand), each
    ``@query``/``@mutation`` method becomes a command within that group.

    Args:
        config: A ``UseCaseAppConfig`` with services.
        app_name: Optional name for the CLI app. Defaults to config.name.

    Returns:
        A ``typer.Typer`` instance ready to be invoked.

    Example::

        cli = create_use_case_cli(UseCaseAppConfig(
            name="project",
            services=[UserService, TaskService],
        ))
        cli()
    """
    from nexusx.use_case.types import UseCaseAppConfig

    if not isinstance(config, UseCaseAppConfig):
        raise TypeError("config must be a UseCaseAppConfig")

    import typer

    name = app_name or config.name
    app = typer.Typer(name=name, help=f"{name} CLI", no_args_is_help=True)

    for service_cls in config.services:
        service_name = _camel_to_snake(service_cls.__name__).replace("_", "-")
        subgroup = typer.Typer(
            name=service_name,
            help=service_cls.__doc__ or f"{service_cls.__name__} commands",
        )

        methods = getattr(service_cls, USE_CASE_METHODS_ATTR, {})
        for method_name, meta in methods.items():
            kind = meta.get("kind", "query") if isinstance(meta, dict) else "query"
            description = meta.get("description", "") if isinstance(meta, dict) else ""

            if not config.enable_mutation and kind == "mutation":
                continue

            method = getattr(service_cls, method_name)
            cmd = _build_command(service_cls, method_name, method, description)
            subgroup.command(name=method_name)(cmd)

        app.add_typer(subgroup)

    return app
