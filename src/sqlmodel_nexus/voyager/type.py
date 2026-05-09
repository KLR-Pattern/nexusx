"""Graph data types for voyager visualization.

Migrated from fastapi-voyager, using standard dataclasses instead of pydantic.dataclasses.
"""
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class NodeBase:
    id: str
    name: str

@dataclass
class FieldInfo:
    name: str
    type_name: str
    from_base: bool = False
    is_object: bool = False
    is_exclude: bool = False
    desc: str = ''

    # pydantic resolve specific fields (kept for template compatibility, defaults to False/None)
    has_pydantic_resolve_meta: bool = False
    is_resolve: bool = False
    is_post: bool = False
    expose_as_info: str | None = None
    send_to_info: list[str] | None = None
    collect_info: list[str] | None = None


@dataclass
class MethodInfo:
    """Method information (analogous to @query/@mutation methods)."""
    name: str
    return_type: str

@dataclass
class Tag(NodeBase):
    routes: list['Route']

@dataclass
class Route(NodeBase):
    module: str
    unique_id: str = ''
    response_schema: str = ''
    is_primitive: bool = True

@dataclass
class ModuleRoute:
    name: str
    fullname: str
    routes: list[Route]
    modules: list['ModuleRoute']

@dataclass
class SchemaNode(NodeBase):
    module: str
    fields: list[FieldInfo] = field(default_factory=list)
    is_entity: bool = False
    queries: list[MethodInfo] = field(default_factory=list)
    mutations: list[MethodInfo] = field(default_factory=list)

@dataclass
class ModuleNode:
    name: str
    fullname: str
    schema_nodes: list[SchemaNode]
    modules: list['ModuleNode']


# Link types:
#   - tag_route: tag -> route
#   - route_to_schema: route -> response model
#   - subset: schema -> schema (subset)
#   - parent: schema -> schema (inheritance)
#   - schema: schema -> schema (field reference)
#   - tag_to_schema: tag -> schema (brief mode)
LinkType = Literal['schema', 'parent', 'tag_route', 'subset', 'route_to_schema', 'tag_to_schema']

@dataclass
class Link:
    # node + field level links
    source: str
    target: str

    # node level links
    source_origin: str
    target_origin: str
    type: LinkType
    label: str | None = None
    style: str | None = None
    loader_fullname: str | None = None

FieldType = Literal['single', 'object', 'all']
PK = "PK"

@dataclass
class CoreData:
    tags: list[Tag]
    routes: list[Route]
    nodes: list[SchemaNode]
    links: list[Link]
    show_fields: FieldType
    module_color: dict[str, str] | None = None
    schema: str | None = None
    show_pydantic_resolve_meta: bool = False
