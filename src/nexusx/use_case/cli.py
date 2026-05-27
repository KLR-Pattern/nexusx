"""CLI generator for UseCaseService via Typer.

Provides ``create_cli()`` to create a Typer app that exposes UseCaseService
methods as CLI commands. Each service becomes a command group, each method
a command within that group.

Usage::

    from nexusx import UseCaseAppConfig, create_cli

    cli = create_cli(UseCaseAppConfig(
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
from typing import Any, get_type_hints

try:
    import typer
except ImportError as exc:
    raise ImportError(
        "typer is required for CLI support: pip install nexusx[cli]"
    ) from exc

from nexusx.use_case.business import USE_CASE_METHODS_ATTR
from nexusx.use_case.server import _serialize_result

_CAMEL_TO_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake(name: str) -> str:
    return _CAMEL_TO_SNAKE_RE.sub("_", name).lower()


def _unwrap_from_context(annotation: Any) -> Any:
    """Extract the inner type from Annotated[T, FromContext()]."""
    from typing import get_args, get_origin

    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        return args[0] if args else annotation
    return annotation


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

    # Build parameter info, mapping FromContext to plain params
    param_infos: list[tuple[str, Any, Any]] = []  # (name, type, default)
    for name, param in sig.parameters.items():
        if name == "cls":
            continue
        anno = hints.get(name, param.annotation)
        if anno is inspect.Parameter.empty:
            anno = str
        anno = _unwrap_from_context(anno)
        default = param.default if param.default is not inspect.Parameter.empty else ...
        param_infos.append((name, anno, default))

    def _command(**kwargs: Any) -> None:
        result = asyncio.run(method(**kwargs))
        print(json.dumps(_serialize_result(result), indent=2, ensure_ascii=False))

    # Set signature for Typer to introspect — use typer.Option so all params
    # become CLI options (--param-name) instead of positional arguments.
    params = []
    for pname, panno, pdefault in param_infos:
        default = typer.Option(pdefault, help=f"{pname}")
        params.append(
            inspect.Parameter(
                pname, inspect.Parameter.KEYWORD_ONLY,
                default=default, annotation=panno,
            )
        )
    _command.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    _command.__doc__ = description or method_name
    _command.__name__ = method_name

    return _command


def create_cli(
    config: Any,
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

        cli = create_cli(UseCaseAppConfig(
            name="project",
            services=[UserService, TaskService],
        ))
        cli()
    """
    from nexusx.use_case.types import UseCaseAppConfig

    if not isinstance(config, UseCaseAppConfig):
        raise TypeError("config must be a UseCaseAppConfig")

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
