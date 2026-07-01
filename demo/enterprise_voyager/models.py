from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx import Relationship as CustomRelationship


class Organization(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    workspaces: list["Workspace"] = Relationship(back_populates="organization")
    departments: list["Department"] = Relationship(back_populates="organization")
    offices: list["Office"] = Relationship(back_populates="organization")
    vendors: list["Vendor"] = Relationship(back_populates="organization")


class Workspace(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    organization_id: int = Field(foreign_key="organization.id")
    organization: Optional[Organization] = Relationship(back_populates="workspaces")
    teams: list["Team"] = Relationship(back_populates="workspace")
    projects: list["Project"] = Relationship(back_populates="workspace")
    dashboards: list["Dashboard"] = Relationship(back_populates="workspace")
    automations: list["AutomationRule"] = Relationship(back_populates="workspace")


class Department(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    organization_id: int = Field(foreign_key="organization.id")
    organization: Optional[Organization] = Relationship(back_populates="departments")
    teams: list["Team"] = Relationship(back_populates="department")
    employees: list["Employee"] = Relationship(back_populates="department")


class Office(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    city: str
    country: str
    organization_id: int = Field(foreign_key="organization.id")
    organization: Optional[Organization] = Relationship(back_populates="offices")
    employees: list["Employee"] = Relationship(back_populates="office")
    rooms: list["Room"] = Relationship(back_populates="office")


class Team(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    workspace_id: int = Field(foreign_key="workspace.id")
    department_id: int | None = Field(default=None, foreign_key="department.id")
    workspace: Optional[Workspace] = Relationship(back_populates="teams")
    department: Optional[Department] = Relationship(back_populates="teams")
    members: list["Employee"] = Relationship(back_populates="team")
    projects: list["Project"] = Relationship(back_populates="team")
    ceremonies: list["Ceremony"] = Relationship(back_populates="team")


class Employee(SQLModel, table=True):
    """员工实体。

    表示系统中的一个**在职**或**离职**员工。一个员工从属于一个 `Department`，
    并通过 `Team` 关联到具体的协作小组；当员工担任管理职责时，`manager_id`
    形成自引用，指向另一个 `Employee` 作为上级。

    ## 关键属性

    - `full_name` — 全名（必填）
    - `email` — 登录邮箱（必填、唯一）
    - `manager_id` — 直属上级，自引用 `Employee.id`
    - 部门/办公点/小组通过外键关联，详见下表

    ## 生命周期

    1. HR 创建员工记录（`Onboarding`）
    2. 完成入职流程，进入 `Active` 状态
    3. 可能进入 `OnLeave` 请假状态
    4. 最终走 `Offboarding` 流程注销

    > **审计**：本实体的写入操作由独立的 `AuditLog` 实体记录，不在本类内维护。

    ## 字段速查

    | 字段 | 类型 | 说明 |
    |------|------|------|
    | `full_name` | `str` | 全名 |
    | `email` | `str` | 登录邮箱 |
    | `department_id` | `int` | 所属部门 |
    | `office_id` | `int` | 办公地点 |
    | `team_id` | `int` | 协作小组 |
    | `manager_id` | `int` | 直属上级（自引用） |

    ### Python 构造

    ```python
    emp = Employee(
        full_name="张三",
        email="zhangsan@example.com",
        department_id=1,
        office_id=2,
        team_id=3,
    )
    ```

    #### 字段命名约定

    `_下划线命名_` 的字段表示内部引用（如 `_internal_state`），普通字段用 `lowercase`。
    命名细节可参考项目的命名规范文档。

    ---

    说明：本字段表用于 demo / 文档展示，实际字段定义以源码为准。可参考
    [SQLModel 关系文档](https://sqlmodel.tiangolo.com/tutorial/relationships/)。

    ## 状态机（stateDiagram）

    ```mermaid
    stateDiagram-v2
        [*] --> Onboarding
        Onboarding --> Active: 完成入职
        Active --> OnLeave: 请假
        OnLeave --> Active: 假期结束
        Active --> Offboarding: 提交离职
        Offboarding --> [*]: 完成离职
        OnLeave --> Offboarding: 假期中离职
    ```

    ## 入职流程（flowchart）

    ```mermaid
    flowchart TD
        A[HR 创建 Employee] --> B{材料齐全?}
        B -->|是| C[开通邮箱/账号]
        B -->|否| A
        C --> D[分配 Department/Office/Team]
        D --> E[指定 Manager]
        E --> F[入职培训]
        F --> G[Active]
    ```

    ## 离职交互（sequenceDiagram）

    ```mermaid
    sequenceDiagram
        participant E as Employee
        participant M as Manager
        participant H as HR
        E->>M: 提交离职申请
        M->>H: 审批通过
        H->>E: 离职清单
        E->>H: 交接完成
        H->>E: 注销账号
    ```
    """

    id: int | None = Field(default=None, primary_key=True)
    full_name: str
    email: str
    department_id: int | None = Field(default=None, foreign_key="department.id")
    office_id: int | None = Field(default=None, foreign_key="office.id")
    team_id: int | None = Field(default=None, foreign_key="team.id")
    manager_id: int | None = Field(default=None, foreign_key="employee.id")
    department: Optional[Department] = Relationship(back_populates="employees")
    office: Optional[Office] = Relationship(back_populates="employees")
    team: Optional[Team] = Relationship(back_populates="members")
    manager: Optional["Employee"] = Relationship(
        sa_relationship_kwargs={"remote_side": "Employee.id"},
        back_populates="reports",
    )
    reports: list["Employee"] = Relationship(back_populates="manager")
    assigned_tasks: list["Task"] = Relationship(
        back_populates="assignee",
        sa_relationship_kwargs={"foreign_keys": "Task.assignee_id"},
    )
    created_tasks: list["Task"] = Relationship(
        back_populates="creator",
        sa_relationship_kwargs={"foreign_keys": "Task.creator_id"},
    )
    comments: list["Comment"] = Relationship(back_populates="author")
    approvals: list["Approval"] = Relationship(back_populates="approver")
    notifications: list["Notification"] = Relationship(back_populates="recipient")
    timesheets: list["Timesheet"] = Relationship(back_populates="employee")
    assets: list["Asset"] = Relationship(back_populates="owner")
    calendars: list["Calendar"] = Relationship(back_populates="owner")
    knowledge_articles: list["KnowledgeArticle"] = Relationship(back_populates="author")


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    workspace_id: int = Field(foreign_key="workspace.id")
    team_id: int | None = Field(default=None, foreign_key="team.id")
    workspace: Optional[Workspace] = Relationship(back_populates="projects")
    team: Optional[Team] = Relationship(back_populates="projects")
    epics: list["Epic"] = Relationship(back_populates="project")
    sprints: list["Sprint"] = Relationship(back_populates="project")
    milestones: list["Milestone"] = Relationship(back_populates="project")
    documents: list["Document"] = Relationship(back_populates="project")
    invoices: list["Invoice"] = Relationship(back_populates="project")
    risks: list["Risk"] = Relationship(back_populates="project")


class Epic(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    project_id: int = Field(foreign_key="project.id")
    project: Optional[Project] = Relationship(back_populates="epics")
    stories: list["Story"] = Relationship(back_populates="epic")


class Story(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    epic_id: int = Field(foreign_key="epic.id")
    epic: Optional[Epic] = Relationship(back_populates="stories")
    tasks: list["Task"] = Relationship(back_populates="story")


class Sprint(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    project_id: int = Field(foreign_key="project.id")
    project: Optional[Project] = Relationship(back_populates="sprints")
    tasks: list["Task"] = Relationship(back_populates="sprint")
    ceremonies: list["Ceremony"] = Relationship(back_populates="sprint")


class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    status: str = "todo"
    sprint_id: int | None = Field(default=None, foreign_key="sprint.id")
    story_id: int | None = Field(default=None, foreign_key="story.id")
    assignee_id: int | None = Field(default=None, foreign_key="employee.id")
    creator_id: int | None = Field(default=None, foreign_key="employee.id")
    parent_task_id: int | None = Field(default=None, foreign_key="task.id")
    sprint: Optional[Sprint] = Relationship(back_populates="tasks")
    story: Optional[Story] = Relationship(back_populates="tasks")
    assignee: Optional[Employee] = Relationship(
        back_populates="assigned_tasks",
        sa_relationship_kwargs={"foreign_keys": "Task.assignee_id"},
    )
    creator: Optional[Employee] = Relationship(
        back_populates="created_tasks",
        sa_relationship_kwargs={"foreign_keys": "Task.creator_id"},
    )
    parent_task: Optional["Task"] = Relationship(
        sa_relationship_kwargs={"remote_side": "Task.id"},
        back_populates="subtasks",
    )
    subtasks: list["Task"] = Relationship(back_populates="parent_task")
    comments: list["Comment"] = Relationship(back_populates="task")
    checklists: list["Checklist"] = Relationship(back_populates="task")
    attachments: list["Attachment"] = Relationship(back_populates="task")
    approvals: list["Approval"] = Relationship(back_populates="task")
    worklogs: list["Worklog"] = Relationship(back_populates="task")
    task_labels: list["TaskLabel"] = Relationship(back_populates="task")
    blockers: list["Dependency"] = Relationship(
        back_populates="blocked_task",
        sa_relationship_kwargs={"foreign_keys": "Dependency.blocked_task_id"},
    )
    depends_on: list["Dependency"] = Relationship(
        back_populates="blocking_task",
        sa_relationship_kwargs={"foreign_keys": "Dependency.blocking_task_id"},
    )
    risks: list["Risk"] = Relationship(back_populates="task")
    __relationships__ = [
        CustomRelationship(
            fk="id",
            target=list["KnowledgeArticle"],
            name="playbooks",
            loader=lambda ids: [[] for _ in ids],
            description="Suggested knowledge base playbooks for tasks",
        )
    ]


class Comment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    body: str
    task_id: int = Field(foreign_key="task.id")
    author_id: int = Field(foreign_key="employee.id")
    task: Optional[Task] = Relationship(back_populates="comments")
    author: Optional[Employee] = Relationship(back_populates="comments")


class Checklist(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    task_id: int = Field(foreign_key="task.id")
    task: Optional[Task] = Relationship(back_populates="checklists")
    items: list["ChecklistItem"] = Relationship(back_populates="checklist")


class ChecklistItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    done: bool = False
    checklist_id: int = Field(foreign_key="checklist.id")
    checklist: Optional[Checklist] = Relationship(back_populates="items")


class Attachment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    file_name: str
    task_id: int = Field(foreign_key="task.id")
    document_id: int | None = Field(default=None, foreign_key="document.id")
    task: Optional[Task] = Relationship(back_populates="attachments")
    document: Optional["Document"] = Relationship(back_populates="attachments")


class Label(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    color: str
    task_labels: list["TaskLabel"] = Relationship(back_populates="label")


class TaskLabel(SQLModel, table=True):
    task_id: int = Field(foreign_key="task.id", primary_key=True)
    label_id: int = Field(foreign_key="label.id", primary_key=True)
    task: Optional[Task] = Relationship(back_populates="task_labels")
    label: Optional[Label] = Relationship(back_populates="task_labels")


class Milestone(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    project_id: int = Field(foreign_key="project.id")
    project: Optional[Project] = Relationship(back_populates="milestones")


class Dependency(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    blocked_task_id: int = Field(foreign_key="task.id")
    blocking_task_id: int = Field(foreign_key="task.id")
    blocked_task: Optional[Task] = Relationship(
        back_populates="blockers",
        sa_relationship_kwargs={"foreign_keys": "Dependency.blocked_task_id"},
    )
    blocking_task: Optional[Task] = Relationship(
        back_populates="depends_on",
        sa_relationship_kwargs={"foreign_keys": "Dependency.blocking_task_id"},
    )


class Approval(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    status: str = "pending"
    task_id: int = Field(foreign_key="task.id")
    approver_id: int = Field(foreign_key="employee.id")
    task: Optional[Task] = Relationship(back_populates="approvals")
    approver: Optional[Employee] = Relationship(back_populates="approvals")


class Worklog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    hours: float
    task_id: int = Field(foreign_key="task.id")
    timesheet_id: int | None = Field(default=None, foreign_key="timesheet.id")
    task: Optional[Task] = Relationship(back_populates="worklogs")
    timesheet: Optional["Timesheet"] = Relationship(back_populates="worklogs")


class Timesheet(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    week_label: str
    employee_id: int = Field(foreign_key="employee.id")
    employee: Optional[Employee] = Relationship(back_populates="timesheets")
    worklogs: list[Worklog] = Relationship(back_populates="timesheet")


class Ceremony(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int = Field(foreign_key="team.id")
    sprint_id: int | None = Field(default=None, foreign_key="sprint.id")
    room_id: int | None = Field(default=None, foreign_key="room.id")
    team: Optional[Team] = Relationship(back_populates="ceremonies")
    sprint: Optional[Sprint] = Relationship(back_populates="ceremonies")
    room: Optional["Room"] = Relationship(back_populates="ceremonies")


class Room(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    office_id: int = Field(foreign_key="office.id")
    office: Optional[Office] = Relationship(back_populates="rooms")
    ceremonies: list[Ceremony] = Relationship(back_populates="room")
    calendars: list["Calendar"] = Relationship(back_populates="room")


class Calendar(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    room_id: int | None = Field(default=None, foreign_key="room.id")
    owner: Optional[Employee] = Relationship(back_populates="calendars")
    room: Optional[Room] = Relationship(back_populates="calendars")
    events: list["CalendarEvent"] = Relationship(back_populates="calendar")


class CalendarEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    calendar_id: int = Field(foreign_key="calendar.id")
    calendar: Optional[Calendar] = Relationship(back_populates="events")


class Document(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    project_id: int | None = Field(default=None, foreign_key="project.id")
    project: Optional[Project] = Relationship(back_populates="documents")
    attachments: list[Attachment] = Relationship(back_populates="document")
    revisions: list["DocumentRevision"] = Relationship(back_populates="document")


class DocumentRevision(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    version: str
    document_id: int = Field(foreign_key="document.id")
    document: Optional[Document] = Relationship(back_populates="revisions")


class Dashboard(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    workspace_id: int = Field(foreign_key="workspace.id")
    workspace: Optional[Workspace] = Relationship(back_populates="dashboards")
    widgets: list["Widget"] = Relationship(back_populates="dashboard")


class Widget(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    dashboard_id: int = Field(foreign_key="dashboard.id")
    dashboard: Optional[Dashboard] = Relationship(back_populates="widgets")


class Notification(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    recipient_id: int = Field(foreign_key="employee.id")
    recipient: Optional[Employee] = Relationship(back_populates="notifications")


class Vendor(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    organization_id: int = Field(foreign_key="organization.id")
    organization: Optional[Organization] = Relationship(back_populates="vendors")
    contracts: list["Contract"] = Relationship(back_populates="vendor")
    assets: list["Asset"] = Relationship(back_populates="vendor")


class Contract(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    code: str
    vendor_id: int = Field(foreign_key="vendor.id")
    vendor: Optional[Vendor] = Relationship(back_populates="contracts")
    invoices: list["Invoice"] = Relationship(back_populates="contract")


class Invoice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    amount: float
    contract_id: int | None = Field(default=None, foreign_key="contract.id")
    project_id: int | None = Field(default=None, foreign_key="project.id")
    contract: Optional[Contract] = Relationship(back_populates="invoices")
    project: Optional[Project] = Relationship(back_populates="invoices")


class Asset(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    vendor_id: int | None = Field(default=None, foreign_key="vendor.id")
    owner: Optional[Employee] = Relationship(back_populates="assets")
    vendor: Optional[Vendor] = Relationship(back_populates="assets")


class Risk(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    project_id: int | None = Field(default=None, foreign_key="project.id")
    task_id: int | None = Field(default=None, foreign_key="task.id")
    project: Optional[Project] = Relationship(back_populates="risks")
    task: Optional[Task] = Relationship(back_populates="risks")


class AutomationRule(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    workspace_id: int = Field(foreign_key="workspace.id")
    workspace: Optional[Workspace] = Relationship(back_populates="automations")


class KnowledgeArticle(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int | None = Field(default=None, foreign_key="employee.id")
    author: Optional[Employee] = Relationship(back_populates="knowledge_articles")
