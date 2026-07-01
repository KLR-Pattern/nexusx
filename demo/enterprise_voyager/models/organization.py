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
    organization: Optional["Organization"] = Relationship(back_populates="workspaces")
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
    organization: Optional["Organization"] = Relationship(back_populates="departments")
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
    organization: Optional["Organization"] = Relationship(back_populates="offices")
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
    workspace: Optional["Workspace"] = Relationship(back_populates="teams")
    department: Optional["Department"] = Relationship(back_populates="teams")
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
    department: Optional["Department"] = Relationship(back_populates="employees")
    office: Optional["Office"] = Relationship(back_populates="employees")
    team: Optional["Team"] = Relationship(back_populates="members")
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


class Room(SQLModel, table=True):
    """会议室实体。

    表示办公点下可预约的物理空间，可被 `Ceremony` 与 `Calendar` 使用。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    office_id: int = Field(foreign_key="office.id")
    office: Optional["Office"] = Relationship(back_populates="rooms")
    ceremonies: list["Ceremony"] = Relationship(back_populates="room")
    calendars: list["Calendar"] = Relationship(back_populates="room")
