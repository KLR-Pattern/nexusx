from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx import Relationship as CustomRelationship


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
    workspace: Optional["Workspace"] = Relationship(back_populates="projects")
    team: Optional["Team"] = Relationship(back_populates="projects")
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
    project: Optional["Project"] = Relationship(back_populates="epics")
    stories: list["Story"] = Relationship(back_populates="epic")


class Story(SQLModel, table=True):
    """用户故事实体。

    表示史诗下可拆分和交付的需求条目，是任务拆解前的业务需求单元。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    epic_id: int = Field(foreign_key="epic.id")
    epic: Optional["Epic"] = Relationship(back_populates="stories")
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
    project: Optional["Project"] = Relationship(back_populates="sprints")
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
    sprint: Optional["Sprint"] = Relationship(back_populates="tasks")
    story: Optional["Story"] = Relationship(back_populates="tasks")
    assignee: Optional["Employee"] = Relationship(
        back_populates="assigned_tasks",
        sa_relationship_kwargs={"foreign_keys": "Task.assignee_id"},
    )
    creator: Optional["Employee"] = Relationship(
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
    task: Optional["Task"] = Relationship(back_populates="comments")
    author: Optional["Employee"] = Relationship(back_populates="comments")


class Checklist(SQLModel, table=True):
    """清单实体。

    表示任务下的一组可勾选验收或执行项，用于跟踪细粒度完成情况。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    task_id: int = Field(foreign_key="task.id")
    task: Optional["Task"] = Relationship(back_populates="checklists")
    items: list["ChecklistItem"] = Relationship(back_populates="checklist")


class ChecklistItem(SQLModel, table=True):
    """清单项实体。

    表示清单中的单个待办或验收步骤，是 `Checklist` 的最小执行单元。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    done: bool = False
    checklist_id: int = Field(foreign_key="checklist.id")
    checklist: Optional["Checklist"] = Relationship(back_populates="items")


class Attachment(SQLModel, table=True):
    """附件实体。

    表示关联到任务或文档的文件资源，可用于补充需求、设计或交付材料。
    """

    id: int | None = Field(default=None, primary_key=True)
    file_name: str
    task_id: int = Field(foreign_key="task.id")
    document_id: int | None = Field(default=None, foreign_key="document.id")
    task: Optional["Task"] = Relationship(back_populates="attachments")
    document: Optional["Document"] = Relationship(back_populates="attachments")


class Milestone(SQLModel, table=True):
    """里程碑实体。

    表示项目中关键时间点或阶段目标，常用于管理计划与对外承诺。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    project_id: int = Field(foreign_key="project.id")
    project: Optional["Project"] = Relationship(back_populates="milestones")


class Dependency(SQLModel, table=True):
    """任务依赖实体。

    表示任务之间的阻塞与被阻塞关系，用于识别交付路径中的前置约束。
    """

    id: int | None = Field(default=None, primary_key=True)
    blocked_task_id: int = Field(foreign_key="task.id")
    blocking_task_id: int = Field(foreign_key="task.id")
    blocked_task: Optional["Task"] = Relationship(
        back_populates="blockers",
        sa_relationship_kwargs={"foreign_keys": "Dependency.blocked_task_id"},
    )
    blocking_task: Optional["Task"] = Relationship(
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
    task: Optional["Task"] = Relationship(back_populates="approvals")
    approver: Optional["Employee"] = Relationship(back_populates="approvals")
