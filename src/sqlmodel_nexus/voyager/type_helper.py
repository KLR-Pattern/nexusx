"""Type helper utilities for voyager visualization.

Migrated from fastapi-voyager, with pydantic_resolve dependencies removed.
"""
import inspect
import logging
import os
from types import UnionType
from typing import Annotated, Any, ForwardRef, Generic, Union, get_args, get_origin

from pydantic import BaseModel

from sqlmodel_nexus.context import AutoLoadInfo, ExposeInfo, ICollector, SendToInfo
from sqlmodel_nexus.voyager.type import FieldInfo

logger = logging.getLogger(__name__)

# Python <3.12 compatibility
try:
    from typing import TypeAliasType
except Exception:
    class _DummyTypeAliasType:
        pass
    TypeAliasType = _DummyTypeAliasType  # type: ignore


def is_list(annotation):
    return getattr(annotation, "__origin__", None) is list


def full_class_name(cls):
    return f"{cls.__module__}.{cls.__qualname__}"


def get_core_types(tp):
    """Get core types from annotation, unwrapping Optional/Union/Annotated/list."""
    def _unwrap_alias(t):
        while isinstance(t, TypeAliasType) or (
            t.__class__.__name__ == 'TypeAliasType' and hasattr(t, '__value__')
        ):
            try:
                t = t.__value__
            except Exception:
                break
        return t

    def _enqueue(items, q):
        for it in items:
            if it is not type(None):
                q.append(it)

    queue: list[object] = [tp]
    result: list[object] = []

    while queue:
        cur = queue.pop(0)
        if cur is type(None):
            continue

        cur = _unwrap_alias(cur)

        if get_origin(cur) is Annotated:
            args = get_args(cur)
            if args:
                queue.append(args[0])
            continue

        orig = get_origin(cur)
        if orig in (Union, UnionType):
            args = get_args(cur)
            _enqueue(args, queue)
            continue

        if is_list(cur):
            args = getattr(cur, "__args__", ())
            if args:
                queue.append(args[0])
            continue

        _cur2 = _unwrap_alias(cur)
        if _cur2 is not cur:
            queue.append(_cur2)
            continue

        result.append(cur)

    return tuple(result)


def get_type_name(anno):
    """Get a human-readable type name string."""
    def name_of(tp):
        origin = get_origin(tp)
        args = get_args(tp)

        if origin is Annotated:
            return name_of(args[0]) if args else 'Annotated'

        if origin is Union:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1 and len(args) == 2:
                return f"Optional[{name_of(non_none[0])}]"
            return f"Union[{', '.join(name_of(a) for a in args)}]"

        if origin is not None:
            origin_name_map = {
                list: 'List',
                dict: 'Dict',
                set: 'Set',
                tuple: 'Tuple',
                frozenset: 'FrozenSet',
            }
            origin_name = origin_name_map.get(origin)
            if origin_name is None:
                origin_name = (
                    getattr(origin, '__name__', None)
                    or str(origin).replace('typing.', '')
                )
            if args:
                return f"{origin_name}[{', '.join(name_of(a) for a in args)}]"
            return origin_name

        if tp is Any:
            return 'Any'
        if tp is None or tp is type(None):
            return 'None'
        if isinstance(tp, type):
            return tp.__name__

        fwd = getattr(tp, '__forward_arg__', None) or getattr(tp, 'arg', None)
        if fwd:
            return str(fwd)

        return (
            str(tp)
            .replace('typing.', '')
            .replace('<class ', '')
            .replace('>', '')
            .replace("'", '')
        )

    return name_of(anno)


def is_inheritance_of_pydantic_base(cls):
    return (
        safe_issubclass(cls, BaseModel)
        and cls is not BaseModel
        and not is_generic_container(cls)
    )


def get_bases_fields(schemas: list[type[BaseModel]]) -> set[str]:
    """Collect field names from a list of BaseModel subclasses."""
    fields: set[str] = set()
    for schema in schemas:
        for k, _ in getattr(schema, 'model_fields', {}).items():
            fields.add(k)
    return fields


def analysis_pydantic_resolve_fields(schema: type[BaseModel], field_name: str) -> dict:
    """Analyze resolve/post/expose/send metadata for a field.

    Checks for resolve_*, post_*, ExposeAs, SendTo, AutoLoad, and Collector.

    Returns a dict with keys matching FieldInfo resolve attributes.
    """
    is_resolve = hasattr(schema, f'resolve_{field_name}')
    is_post = hasattr(schema, f'post_{field_name}')
    expose_as_info: str | None = None
    send_to_info_list: list[str] = []
    post_collector: list[str] = []

    field_info = schema.model_fields.get(field_name)
    if field_info:
        for meta in field_info.metadata:
            if isinstance(meta, AutoLoadInfo):
                is_resolve = True
            if isinstance(meta, ExposeInfo):
                expose_as_info = meta.alias
            if isinstance(meta, SendToInfo):
                if isinstance(meta.collector_name, str):
                    send_to_info_list.append(meta.collector_name)
                else:
                    send_to_info_list.extend(meta.collector_name)

    if is_post:
        post_method = getattr(schema, f'post_{field_name}')
        for _, param in inspect.signature(post_method).parameters.items():
            if isinstance(param.default, ICollector):
                post_collector.append(param.default.alias)

    send_to_info = list(set(send_to_info_list)) if send_to_info_list else None
    has_meta = any([is_resolve, is_post, expose_as_info, send_to_info])

    return {
        "has_pydantic_resolve_meta": has_meta,
        "is_resolve": is_resolve,
        "is_post": is_post,
        "expose_as_info": expose_as_info,
        "send_to_info": send_to_info,
        "collect_info": None if len(post_collector) == 0 else post_collector,
    }


def get_pydantic_fields(schema: type[BaseModel], bases_fields: set[str]) -> list[FieldInfo]:
    """Extract pydantic model fields with metadata."""
    def _is_object(anno):
        _types = get_core_types(anno)
        return any(is_inheritance_of_pydantic_base(t) for t in _types if t)

    fields: list[FieldInfo] = []
    for k, v in schema.model_fields.items():
        anno = v.annotation
        resolve_meta = analysis_pydantic_resolve_fields(schema, k)
        fields.append(FieldInfo(
            is_object=_is_object(anno),
            name=k,
            from_base=k in bases_fields,
            type_name=get_type_name(anno),
            is_exclude=bool(v.exclude),
            desc=v.description or '',
            has_pydantic_resolve_meta=resolve_meta["has_pydantic_resolve_meta"],
            is_resolve=resolve_meta["is_resolve"],
            is_post=resolve_meta["is_post"],
            expose_as_info=resolve_meta["expose_as_info"],
            send_to_info=resolve_meta["send_to_info"],
            collect_info=resolve_meta["collect_info"],
        ))
    return fields


def get_vscode_link(kls, online_repo_url: str | None = None) -> str:
    """Build a VSCode deep link to the class definition."""
    try:
        source_file = inspect.getfile(kls)
        _lines, start_line = inspect.getsourcelines(kls)

        distro = os.environ.get("WSL_DISTRO_NAME")
        if online_repo_url:
            cwd = os.getcwd()
            relative_path = os.path.relpath(source_file, cwd)
            return f"{online_repo_url}/{relative_path}#L{start_line}"
        if distro:
            return f"vscode://vscode-remote/wsl+{distro}{source_file}:{start_line}"

        if source_file.startswith('/mnt/') and len(source_file) > 6:
            parts = source_file.split('/')
            if len(parts) >= 4 and len(parts[2]) == 1:
                drive = parts[2].upper()
                rest = parts[3:]
                win_path = drive + ':\\' + '\\'.join(rest)
                return f"vscode://file/{win_path}:{start_line}"

        return f"vscode://file/{source_file}:{start_line}"
    except Exception:
        return ""


def get_source(kls):
    """Get source code for a class."""
    try:
        source = inspect.getsource(kls)
        return source
    except Exception:
        return "failed to get source"


def safe_issubclass(kls, target_kls):
    """Safe issubclass that handles ForwardRef and other edge cases."""
    try:
        return issubclass(kls, target_kls)
    except TypeError:
        if isinstance(kls, ForwardRef):
            logger.error(
                f'{str(kls)} is a ForwardRef, '
                f'not a subclass of {target_kls.__module__}:{target_kls.__qualname__}'
            )
        elif isinstance(kls, type):
            logger.debug(
                f'{kls.__module__}:{kls.__qualname__} is not subclass of '
                f'{target_kls.__module__}:{target_kls.__qualname__}'
            )
        return False


def update_forward_refs(kls):
    """Recursively update forward references in Pydantic models."""
    for shelled_type in get_core_types(kls):
        if safe_issubclass(shelled_type, BaseModel):
            try:
                shelled_type.model_rebuild()
            except Exception:
                pass
            # Recurse into fields
            for field in shelled_type.model_fields.values():
                update_forward_refs(field.annotation)


def is_generic_container(cls):
    """Check if a class is an unresolved generic container."""
    try:
        return (
            hasattr(cls, '__bases__')
            and Generic in cls.__bases__
            and hasattr(cls, '__parameters__')
            and bool(cls.__parameters__)
        )
    except (TypeError, AttributeError):
        return False


def is_non_pydantic_type(tp):
    """Check if a type does not contain any Pydantic BaseModel subclasses."""
    for schema in get_core_types(tp):
        if schema and safe_issubclass(schema, BaseModel):
            return False
    return True
