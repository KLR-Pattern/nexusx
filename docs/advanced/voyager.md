# Voyager Visualization

Interactive web-based visualization of your UseCase service structure and ER entity relationships. Mount it to FastAPI and explore your model in the browser.

## Step 1: Mount Voyager

```python
from nexusx.voyager import create_use_case_voyager
from nexusx.use_case import UseCaseAppConfig
from fastapi import FastAPI

voyager = create_use_case_voyager(
    apps=[
        UseCaseAppConfig(name="project", services=[SprintService, TaskService]),
    ],
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

## Step 2: Share Configuration with MCP

Voyager and MCP use the same `UseCaseAppConfig` — one configuration, two presentations:

```python
from nexusx.use_case import UseCaseAppConfig, create_use_case_graphql_mcp_server
from nexusx.voyager import create_use_case_voyager

apps = [
    UseCaseAppConfig(
        name="project",
        services=[SprintService, TaskService],
    ),
]

# MCP service (AI agents)
mcp = create_use_case_graphql_mcp_server(apps=apps, name="API")

# Voyager visualization (developers)
voyager = create_use_case_voyager(apps=apps, er_manager=er)

app = FastAPI()
app.mount("/mcp", mcp)
app.mount("/voyager", voyager)
```

AI agents discover and call services via MCP. Developers explore the same services interactively via Voyager. Both see the same structure.

## Configuration

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `apps` | `list[UseCaseAppConfig]` | — | Application configuration list |
| `er_manager` | `ErManager \| None` | `None` | ErManager instance for ER diagram |
| `name` | `str` | `"UseCase API"` | Project name in UI title |
| `module_colors` | `dict[str, str] \| None` | `None` | Custom colors for service modules |
| `initial_page_policy` | `"first" / "full" / "empty"` | `"first"` | Initial page loading policy |
| `online_repo_url` | `str \| None` | `None` | Repository URL for source code links |
| `version` | `str` | `"1.0.0"` | Version in UI |

### REST endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/dot` | GET | Service dependency graph in DOT format |
| `/dot-search` | GET | Searchable and filterable DOT graph |
| `/er-diagram` | GET | Mermaid ER diagram (requires `er_manager`) |
| `/source` | GET | Source code information for service methods |

## Recap

- Mount Voyager to FastAPI with a single `app.mount()` call
- Service graph shows UseCaseService methods, DTOs, and dependencies
- ER diagram shows entity relationships and DefineSubset mappings
- Shares the same `UseCaseAppConfig` as MCP — one config, two presentations

## Next Steps

- [ER Diagram Visualization](../guide/er_diagram_visual.md) — Mermaid output and Voyager basics
- [UseCase Service](./use_case_service.md) — Define the services that Voyager displays
- [MCP Service](./mcp_service.md) — Expose the same services to AI agents
