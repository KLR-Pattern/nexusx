"""DefineSubset DTOs for the Core API demo.

Progressive complexity from simple field selection to full cross-layer data flow.
Each level builds on the previous one, matching the pydantic-resolve README pattern.

Level 1: Basic field selection + FK hiding (UserSummary)
Level 2: Implicit relationship loading (TaskSummary)
Level 3: post_* derived fields (SprintSummary)
Level 4: ExposeAs + SendTo + Collector cross-layer flow (SprintDetail, TaskDetail)
Level 5: Custom __relationships__ + implicit auto-load (TaskWithTags, SprintWithTags)
"""


from typing import Annotated

from demo.core_api.models import Sprint, Tag, Task, User
from nexusx import Collector, DefineSubset, SubsetConfig
from nexusx.loader.pagination import Paged

# ──────────────────────────────────────────────────────────
# Level 1: Basic DefineSubset — field selection + FK hiding
# ──────────────────────────────────────────────────────────

class UserSummary(DefineSubset):
    """Simple user DTO with selected fields."""
    __subset__ = SubsetConfig(kls=User, fields=['id', 'name'])


# ──────────────────────────────────────────────────────────
# Level 2: Implicit relationship loading
# ──────────────────────────────────────────────────────────

class TaskSummary(DefineSubset):
    """Task DTO that auto-loads its owner implicitly.

    The 'owner' field name matches the 'owner' relationship on the Task
    entity. The Resolver detects this automatically via LoaderRegistry:
    - Matches field name 'owner' to Task.owner relationship (many-to-one)
    - Uses the FK field 'owner_id' to load via DataLoader
    - Converts the raw SQLModel User to UserSummary DTO

    No AutoLoad() annotation needed — it's inferred from the relationship.
    """
    __subset__ = SubsetConfig(
        kls=Task,
        fields=['id', 'title', 'sprint_id', 'owner_id', 'done'],
    )

    owner: UserSummary | None = None


# ──────────────────────────────────────────────────────────
# Level 3: post_* — derived fields after children are resolved
# ──────────────────────────────────────────────────────────

class SprintSummary(DefineSubset):
    """Sprint DTO with derived fields computed after tasks are loaded.

    Execution order per SprintSummary:
    1. Implicit AutoLoad — loads tasks via DataLoader and converts to DTOs
    2. Each TaskSummary.owner — implicit AutoLoad loads owners via DataLoader
    3. post_task_count — len(self.tasks) after tasks are ready
    4. post_contributor_names — unique owner names after owners are ready
    """
    __subset__ = SubsetConfig(kls=Sprint, fields=['id', 'name'])

    tasks: list[TaskSummary] = []
    task_count: int = 0
    contributor_names: list[str] = []

    def post_task_count(self):
        return len(self.tasks)

    def post_contributor_names(self):
        names = {t.owner.name for t in self.tasks if t.owner}
        return sorted(names)


# ──────────────────────────────────────────────────────────
# Level 4: ExposeAs + SendTo + Collector — cross-layer data flow
# ──────────────────────────────────────────────────────────

class TaskDetail(DefineSubset):
    """Task DTO with ancestor context and upward aggregation.

    Uses SubsetConfig to declare send_to metadata declaratively
    instead of annotating in the class body.

    - 'owner' implicitly auto-loads (matches Task.owner relationship)
    - owner is marked with SendTo('contributors') via SubsetConfig
    - post_full_title uses ancestor_context to get the sprint name
      exposed by SprintDetail.name via ExposeAs('sprint_name').
    """
    __subset__ = SubsetConfig(
        kls=Task,
        fields=['id', 'title', 'sprint_id', 'owner_id', 'done'],
        send_to=[('owner', 'contributors')],
    )

    owner: UserSummary | None = None
    full_title: str = ""

    def post_full_title(self, ancestor_context=None):
        if ancestor_context is None:
            ancestor_context = {}
        sprint_name = ancestor_context.get('sprint_name', 'unknown')
        return f"{sprint_name} / {self.title}"


class SprintDetail(DefineSubset):
    """Sprint DTO demonstrating full cross-layer data flow.

    Uses SubsetConfig to declare expose_as metadata declaratively
    instead of annotating in the class body.

    - ExposeAs('sprint_name') exposes name to all descendants
    - 'tasks' implicitly auto-loads (matches Sprint.tasks relationship)
    - Collector('contributors') collects owner values from TaskDetail
      via SendTo('contributors')
    """
    __subset__ = SubsetConfig(
        kls=Sprint,
        fields=['id', 'name'],
        expose_as=[('name', 'sprint_name')],
    )

    tasks: list[TaskDetail] = []
    contributors: list[UserSummary] = []

    def post_contributors(self, collector=Collector('contributors')):
        return collector.values()


# ──────────────────────────────────────────────────────────
# Level 5: Custom __relationships__ + implicit auto-load
# ──────────────────────────────────────────────────────────

class TagDTO(DefineSubset):
    """Tag DTO for the custom relationship."""
    __subset__ = SubsetConfig(kls=Tag, fields=['id', 'name'])


class TaskWithTags(DefineSubset):
    """Task DTO that loads tags via a custom __relationships__ loader.

    Task defines `__relationships__` with a 'tags' entry that uses
    a hand-written async loader (no ORM association table needed).

    The 'tags' field name matches the custom relationship name in
    `Task.__relationships__`, and its type (TagDTO) is compatible
    with the relationship target (Tag), so it's auto-loaded.
    """
    __subset__ = SubsetConfig(
        kls=Task,
        fields=['id', 'title', 'sprint_id', 'owner_id', 'done'],
    )

    owner: UserSummary | None = None
    tags: list[TagDTO] = []
    tag_count: int = 0

    def post_tag_count(self):
        return len(self.tags)


class SprintWithTags(DefineSubset):
    """Sprint DTO with tasks that include custom-loaded tags.

    Demonstrates ORM relationships (sprint -> tasks, task -> owner)
    working alongside custom relationships (task -> tags) in a
    single response tree.
    """
    __subset__ = SubsetConfig(kls=Sprint, fields=['id', 'name'])

    tasks: list[TaskWithTags] = []
    task_count: int = 0

    def post_task_count(self):
        return len(self.tasks)


# ──────────────────────────────────────────────────────────
# Level 6: Paged — declarative top-N on an ER-relationship field
# ──────────────────────────────────────────────────────────

class SprintTopTasks(DefineSubset):
    """Sprint DTO with a Paged tasks field (top-N, fixed).

    ``tasks`` carries ``Paged(limit=2)`` (order omitted → uses
    Sprint.__pagination_orders__ default "NEWEST"); the Resolver slices
    per-parent via the page_loader (ROW_NUMBER). Paged is declarative and
    fixed at the field — runtime input belongs on a UseCase method signature,
    not Resolver context.
    """
    __subset__ = SubsetConfig(kls=Sprint, fields=['id', 'name'])

    tasks: Annotated[list[TaskSummary], Paged(limit=2)] = []
