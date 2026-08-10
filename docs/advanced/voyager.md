# Voyager Visualization

Interactive web-based visualization of your UseCase service structure and ER entity relationships. Mount it to FastAPI and explore your model in the browser.

## Step 1: Mount Voyager

```python
from nexusx.voyager import create_use_case_voyager
from fastapi import FastAPI

voyager = create_use_case_voyager(
    services=[SprintService, TaskService],
    er_manager=er,  # Optional: show ER diagram alongside service graph
)

app = FastAPI()
app.mount("/voyager", voyager)
```

Visit `http://localhost:8000/voyager`. You'll see two views:

### Service graph

Displays your UseCaseService methods, their parameters, return types, and inter-service dependencies:

- Method signatures in SDL format
- DTO type definitions
- Cross-service call relationships

### ER entity diagram

When you pass `er_manager`, Voyager shows the full entity relationship graph:

- SQLModel entities and their fields
- ORM relationships (ForeignKey / Relationship)
- Custom relationships (`__relationships__`)
- DefineSubset DTO → source entity mappings

```python
class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title", "owner_id"))
```

Voyager displays the `TaskDTO` → `Task` subset relationship along with the selected fields.

## Step 2: Reuse the Same Services with MCP

Voyager accepts a service list while MCP wraps that same list in
`UseCaseAppConfig`:

```python
from nexusx.use_case import UseCaseAppConfig, create_use_case_mcp_server
from nexusx.voyager import create_use_case_voyager

config = UseCaseAppConfig(
    name="project",
    services=[SprintService, TaskService],
)

# MCP service (AI agents)
mcp = create_use_case_mcp_server(apps=[config], name="API")

# Voyager visualization (developers)
voyager = create_use_case_voyager(services=config.services, er_manager=er)

app = FastAPI()
app.mount("/mcp", mcp)
app.mount("/voyager", voyager)
```

AI agents discover and call services via MCP. Developers explore the same services interactively via Voyager. Both see the same structure.

## Configuration

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `services` | `list[type[UseCaseService]]` | — | Services to visualize |
| `er_manager` | `ErManager \| None` | `None` | ErManager instance for ER diagram |
| `name` | `str` | `"UseCase API"` | Project name in UI title |
| `module_color` | `dict[str, str] \| None` | `None` | Custom colors for service modules |
| `initial_page_policy` | `"first" / "full" / "empty"` | `"first"` | Initial page loading policy |
| `online_repo_url` | `str \| None` | `None` | Repository URL for source code links |
| `version` | `str` | `"1.0.0"` | Version in UI |
| `gzip_minimum_size` | `int \| None` | `500` | GZip threshold; negative disables it |

### REST endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/dot` | GET | Service dependency graph in DOT format |
| `/dot-search` | POST | Search service and DTO nodes |
| `/er-diagram` | POST | Render ER diagram data (requires `er_manager`) |
| `/er-diagram-subgraph` | POST | Render one entity's neighborhood |
| `/source` | POST | Source code information for a schema node |
| `/docstring` | POST | Docstring for the About panel |

## Recap

- Mount Voyager to FastAPI with a single `app.mount()` call
- Service graph shows UseCaseService methods, DTOs, and dependencies
- ER diagram shows entity relationships and DefineSubset mappings
- Reuses the same `UseCaseService` classes as MCP

## Next Steps

- [ER Diagram Visualization](../guide/er_diagram_visual.md) — Mermaid output and Voyager basics
- [UseCase Service](./use_case_service.md) — Define the services that Voyager displays
- [MCP Service](./mcp_service.md) — Expose the same services to AI agents
