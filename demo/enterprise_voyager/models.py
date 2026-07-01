from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx import Relationship as CustomRelationship


class Organization(SQLModel, table=True):
    """组织实体。

    表示企业租户及其顶层业务边界，是 `Workspace`、`Department`、`Office`
    和 `Vendor` 的共同归属节点。

    ## 关键关系

    - 拥有多个 `Workspace`
    - 拥有多个 `Department`
    - 拥有多个 `Office`
    - 管理多个 `Vendor`

    ## 结构概览

    ```mermaid
    flowchart TD
        Organization --> Workspace
        Organization --> Department
        Organization --> Office
        Organization --> Vendor
    ```
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    workspaces: list["Workspace"] = Relationship(back_populates="organization")
    departments: list["Department"] = Relationship(back_populates="organization")
    offices: list["Office"] = Relationship(back_populates="organization")
    vendors: list["Vendor"] = Relationship(back_populates="organization")


class Workspace(SQLModel, table=True):
    """工作区实体。

    用于承载团队、项目、仪表盘与自动化规则，是组织内协作活动的主要容器。

    ## 关键关系

    - 从属于一个 `Organization`
    - 管理多个 `Team`
    - 管理多个 `Project`
    - 承载多个 `Dashboard` 与 `AutomationRule`
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    organization_id: int = Field(foreign_key="organization.id")
    organization: Optional[Organization] = Relationship(back_populates="workspaces")
    teams: list["Team"] = Relationship(back_populates="workspace")
    projects: list["Project"] = Relationship(back_populates="workspace")
    dashboards: list["Dashboard"] = Relationship(back_populates="workspace")
    automations: list["AutomationRule"] = Relationship(back_populates="workspace")


class Department(SQLModel, table=True):
    """部门实体。

    表示组织内的人力归属与管理单元，为员工与团队提供行政维度的挂靠关系。

    ## 关键关系

    - 从属于一个 `Organization`
    - 关联多个 `Team`
    - 关联多个 `Employee`
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    organization_id: int = Field(foreign_key="organization.id")
    organization: Optional[Organization] = Relationship(back_populates="departments")
    teams: list["Team"] = Relationship(back_populates="department")
    employees: list["Employee"] = Relationship(back_populates="department")


class Office(SQLModel, table=True):
    """办公点实体。

    表示组织在某个城市或国家的物理办公地点，承载员工与会议室等线下资源。

    ## 关键关系

    - 从属于一个 `Organization`
    - 容纳多个 `Employee`
    - 包含多个 `Room`
    """

    id: int | None = Field(default=None, primary_key=True)
    city: str
    country: str
    organization_id: int = Field(foreign_key="organization.id")
    organization: Optional[Organization] = Relationship(back_populates="offices")
    employees: list["Employee"] = Relationship(back_populates="office")
    rooms: list["Room"] = Relationship(back_populates="office")


class Team(SQLModel, table=True):
    """团队实体。

    表示工作区下参与项目交付的协作小组，连接部门维度与项目执行维度。

    ## 关键关系

    - 从属于一个 `Workspace`
    - 可选关联一个 `Department`
    - 拥有多个 `Employee` 成员
    - 参与多个 `Project` 与 `Ceremony`
    """

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
    """项目实体。

    聚合史诗、迭代、里程碑、文档、发票与风险信息，是业务交付的核心对象。

    ## 关键关系

    - 从属于一个 `Workspace`
    - 可选归属一个 `Team`
    - 包含多个 `Epic`、`Sprint`、`Milestone`
    - 关联 `Document`、`Invoice` 与 `Risk`

    ## 交付分解

    ```mermaid
    flowchart TD
        Project --> Epic
        Epic --> Story
        Story --> Task
        Project --> Sprint
        Sprint --> Task
        Project --> Milestone
    ```
    """

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
    """史诗实体。

    表示项目中的高层需求或目标主题，用于组织一组相关的 `Story`。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    project_id: int = Field(foreign_key="project.id")
    project: Optional[Project] = Relationship(back_populates="epics")
    stories: list["Story"] = Relationship(back_populates="epic")


class Story(SQLModel, table=True):
    """用户故事实体。

    表示史诗下可拆分和交付的需求条目，是任务拆解前的业务需求单元。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    epic_id: int = Field(foreign_key="epic.id")
    epic: Optional[Epic] = Relationship(back_populates="stories")
    tasks: list["Task"] = Relationship(back_populates="story")


class Sprint(SQLModel, table=True):
    """迭代实体。

    表示项目在一段时间内的计划与执行窗口，用于收拢任务和团队活动。

    ## 关键关系

    - 从属于一个 `Project`
    - 包含多个 `Task`
    - 关联多个 `Ceremony`
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    project_id: int = Field(foreign_key="project.id")
    project: Optional[Project] = Relationship(back_populates="sprints")
    tasks: list["Task"] = Relationship(back_populates="sprint")
    ceremonies: list["Ceremony"] = Relationship(back_populates="sprint")


class Task(SQLModel, table=True):
    """任务实体。

    表示可分配、可跟踪、可依赖的执行项，连接需求、人员、审批、评论与工时。

    ## 关键属性

    - `status` — 当前任务状态
    - `assignee_id` — 执行人
    - `creator_id` — 创建人
    - `parent_task_id` — 父任务，自引用形成子任务树

    ## 关键关系

    - 可归属 `Sprint` 与 `Story`
    - 可关联 `Comment`、`Checklist`、`Attachment`
    - 可关联 `Approval`、`Worklog`、`Risk`
    - 通过 `Dependency` 表示阻塞关系

    ## 生命周期

    1. 创建任务
    2. 指派执行人
    3. 进入执行中
    4. 完成并通过审批

    ## 状态流转

    ```mermaid
    stateDiagram-v2
        [*] --> todo
        todo --> in_progress: 开始处理
        in_progress --> blocked: 出现阻塞
        blocked --> in_progress: 解除阻塞
        in_progress --> review: 提交验收
        review --> done: 审批通过
        review --> in_progress: 打回修改
        done --> [*]
    ```
    """

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
    """评论实体。

    记录员工围绕任务产生的讨论内容，用于沉淀协作过程中的上下文信息。
    """

    id: int | None = Field(default=None, primary_key=True)
    body: str
    task_id: int = Field(foreign_key="task.id")
    author_id: int = Field(foreign_key="employee.id")
    task: Optional[Task] = Relationship(back_populates="comments")
    author: Optional[Employee] = Relationship(back_populates="comments")


class Checklist(SQLModel, table=True):
    """清单实体。

    表示任务下的一组可勾选验收或执行项，用于跟踪细粒度完成情况。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    task_id: int = Field(foreign_key="task.id")
    task: Optional[Task] = Relationship(back_populates="checklists")
    items: list["ChecklistItem"] = Relationship(back_populates="checklist")


class ChecklistItem(SQLModel, table=True):
    """清单项实体。

    表示清单中的单个待办或验收步骤，是 `Checklist` 的最小执行单元。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    done: bool = False
    checklist_id: int = Field(foreign_key="checklist.id")
    checklist: Optional[Checklist] = Relationship(back_populates="items")


class Attachment(SQLModel, table=True):
    """附件实体。

    表示关联到任务或文档的文件资源，可用于补充需求、设计或交付材料。
    """

    id: int | None = Field(default=None, primary_key=True)
    file_name: str
    task_id: int = Field(foreign_key="task.id")
    document_id: int | None = Field(default=None, foreign_key="document.id")
    task: Optional[Task] = Relationship(back_populates="attachments")
    document: Optional["Document"] = Relationship(back_populates="attachments")


class Label(SQLModel, table=True):
    """标签实体。

    表示用于任务分类和筛选的命名标记，通常通过颜色与名称提升可视化识别度。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    color: str
    task_labels: list["TaskLabel"] = Relationship(back_populates="label")


class TaskLabel(SQLModel, table=True):
    """任务标签关联实体。

    维护 `Task` 与 `Label` 之间的多对多关系，是任务分类体系的中间表。
    """

    task_id: int = Field(foreign_key="task.id", primary_key=True)
    label_id: int = Field(foreign_key="label.id", primary_key=True)
    task: Optional[Task] = Relationship(back_populates="task_labels")
    label: Optional[Label] = Relationship(back_populates="task_labels")


class Milestone(SQLModel, table=True):
    """里程碑实体。

    表示项目中关键时间点或阶段目标，常用于管理计划与对外承诺。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    project_id: int = Field(foreign_key="project.id")
    project: Optional[Project] = Relationship(back_populates="milestones")


class Dependency(SQLModel, table=True):
    """任务依赖实体。

    表示任务之间的阻塞与被阻塞关系，用于识别交付路径中的前置约束。
    """

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
    """审批实体。

    表示任务在流程节点上的审批结果与责任人，用于控制任务从执行到验收的过渡。
    """

    id: int | None = Field(default=None, primary_key=True)
    status: str = "pending"
    task_id: int = Field(foreign_key="task.id")
    approver_id: int = Field(foreign_key="employee.id")
    task: Optional[Task] = Relationship(back_populates="approvals")
    approver: Optional[Employee] = Relationship(back_populates="approvals")


class Worklog(SQLModel, table=True):
    """工时记录实体。

    表示任务上登记的实际投入工时，是时间核算与绩效统计的基础数据。
    """

    id: int | None = Field(default=None, primary_key=True)
    hours: float
    task_id: int = Field(foreign_key="task.id")
    timesheet_id: int | None = Field(default=None, foreign_key="timesheet.id")
    task: Optional[Task] = Relationship(back_populates="worklogs")
    timesheet: Optional["Timesheet"] = Relationship(back_populates="worklogs")


class Timesheet(SQLModel, table=True):
    """工时表实体。

    按员工与周期汇总多个工时记录，用于周度或月度的人力投入统计。
    """

    id: int | None = Field(default=None, primary_key=True)
    week_label: str
    employee_id: int = Field(foreign_key="employee.id")
    employee: Optional[Employee] = Relationship(back_populates="timesheets")
    worklogs: list[Worklog] = Relationship(back_populates="timesheet")


class Ceremony(SQLModel, table=True):
    """敏捷会议实体。

    表示团队例会、评审或回顾等活动安排，连接团队、迭代与会议室资源。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int = Field(foreign_key="team.id")
    sprint_id: int | None = Field(default=None, foreign_key="sprint.id")
    room_id: int | None = Field(default=None, foreign_key="room.id")
    team: Optional[Team] = Relationship(back_populates="ceremonies")
    sprint: Optional[Sprint] = Relationship(back_populates="ceremonies")
    room: Optional["Room"] = Relationship(back_populates="ceremonies")


class Room(SQLModel, table=True):
    """会议室实体。

    表示办公点下可预约的物理空间，可被 `Ceremony` 与 `Calendar` 使用。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    office_id: int = Field(foreign_key="office.id")
    office: Optional[Office] = Relationship(back_populates="rooms")
    ceremonies: list[Ceremony] = Relationship(back_populates="room")
    calendars: list["Calendar"] = Relationship(back_populates="room")


class Calendar(SQLModel, table=True):
    """日历实体。

    表示员工或会议室维度的日程容器，用于组织多个 `CalendarEvent`。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    room_id: int | None = Field(default=None, foreign_key="room.id")
    owner: Optional[Employee] = Relationship(back_populates="calendars")
    room: Optional[Room] = Relationship(back_populates="calendars")
    events: list["CalendarEvent"] = Relationship(back_populates="calendar")


class CalendarEvent(SQLModel, table=True):
    """日历事件实体。

    表示某个日历中的单次事件安排，是会议、提醒或占用时段的具体记录。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    calendar_id: int = Field(foreign_key="calendar.id")
    calendar: Optional[Calendar] = Relationship(back_populates="events")


class Document(SQLModel, table=True):
    """文档实体。

    表示项目过程中的知识、方案或交付文档，可附带附件并维护多个版本。

    ## 关键关系

    - 可归属一个 `Project`
    - 拥有多个 `Attachment`
    - 拥有多个 `DocumentRevision`
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    project_id: int | None = Field(default=None, foreign_key="project.id")
    project: Optional[Project] = Relationship(back_populates="documents")
    attachments: list[Attachment] = Relationship(back_populates="document")
    revisions: list["DocumentRevision"] = Relationship(back_populates="document")


class DocumentRevision(SQLModel, table=True):
    """文档版本实体。

    表示文档随时间演进的版本快照，用于追踪知识内容的历史变更。
    """

    id: int | None = Field(default=None, primary_key=True)
    version: str
    document_id: int = Field(foreign_key="document.id")
    document: Optional[Document] = Relationship(back_populates="revisions")


class Dashboard(SQLModel, table=True):
    """仪表盘实体。

    表示工作区下聚合展示指标的小面板集合，用于集中观察项目或团队状态。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    workspace_id: int = Field(foreign_key="workspace.id")
    workspace: Optional[Workspace] = Relationship(back_populates="dashboards")
    widgets: list["Widget"] = Relationship(back_populates="dashboard")


class Widget(SQLModel, table=True):
    """组件实体。

    表示仪表盘中的单个可视化卡片，是指标、图表或摘要信息的最小展示单元。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    dashboard_id: int = Field(foreign_key="dashboard.id")
    dashboard: Optional[Dashboard] = Relationship(back_populates="widgets")


class Notification(SQLModel, table=True):
    """通知实体。

    表示发送给员工的站内提醒消息，用于同步审批、任务或系统状态变更。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    recipient_id: int = Field(foreign_key="employee.id")
    recipient: Optional[Employee] = Relationship(back_populates="notifications")


class Vendor(SQLModel, table=True):
    """供应商实体。

    表示与组织合作的外部服务或设备提供方，可关联合同与资产来源。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    organization_id: int = Field(foreign_key="organization.id")
    organization: Optional[Organization] = Relationship(back_populates="vendors")
    contracts: list["Contract"] = Relationship(back_populates="vendor")
    assets: list["Asset"] = Relationship(back_populates="vendor")


class Contract(SQLModel, table=True):
    """合同实体。

    表示与供应商签署的业务合同记录，是发票和采购关系的上游业务对象。
    """

    id: int | None = Field(default=None, primary_key=True)
    code: str
    vendor_id: int = Field(foreign_key="vendor.id")
    vendor: Optional[Vendor] = Relationship(back_populates="contracts")
    invoices: list["Invoice"] = Relationship(back_populates="contract")


class Invoice(SQLModel, table=True):
    """发票实体。

    表示合同或项目相关的财务结算记录，可同时连接采购与项目交付场景。
    """

    id: int | None = Field(default=None, primary_key=True)
    amount: float
    contract_id: int | None = Field(default=None, foreign_key="contract.id")
    project_id: int | None = Field(default=None, foreign_key="project.id")
    contract: Optional[Contract] = Relationship(back_populates="invoices")
    project: Optional[Project] = Relationship(back_populates="invoices")


class Asset(SQLModel, table=True):
    """资产实体。

    表示归属员工或供应商来源的设备资产，用于管理设备分配和来源追踪。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    vendor_id: int | None = Field(default=None, foreign_key="vendor.id")
    owner: Optional[Employee] = Relationship(back_populates="assets")
    vendor: Optional[Vendor] = Relationship(back_populates="assets")


class Risk(SQLModel, table=True):
    """风险实体。

    表示项目或任务上的潜在问题与风险点，用于提前识别影响交付的不确定因素。

    ## 风险升级路径

    ```mermaid
    flowchart LR
        Identified[识别] --> Assessed[评估]
        Assessed --> Mitigated[缓解]
        Assessed --> Escalated[升级]
        Escalated --> Closed[关闭]
        Mitigated --> Closed
    ```
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    project_id: int | None = Field(default=None, foreign_key="project.id")
    task_id: int | None = Field(default=None, foreign_key="task.id")
    project: Optional[Project] = Relationship(back_populates="risks")
    task: Optional[Task] = Relationship(back_populates="risks")


class AutomationRule(SQLModel, table=True):
    """自动化规则实体。

    表示工作区内的流程自动执行配置，用于在特定条件下自动驱动协作流程。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    workspace_id: int = Field(foreign_key="workspace.id")
    workspace: Optional[Workspace] = Relationship(back_populates="automations")


class KnowledgeArticle(SQLModel, table=True):
    """知识文章实体。

    表示由员工撰写和维护的内部知识内容，是组织沉淀经验与规范的载体。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int | None = Field(default=None, foreign_key="employee.id")
    author: Optional[Employee] = Relationship(back_populates="knowledge_articles")
