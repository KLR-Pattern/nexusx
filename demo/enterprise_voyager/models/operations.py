from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx import Relationship as CustomRelationship


class Worklog(SQLModel, table=True):
    """工时记录实体。

    表示任务上登记的实际投入工时，是时间核算与绩效统计的基础数据。
    """

    id: int | None = Field(default=None, primary_key=True)
    hours: float
    task_id: int = Field(foreign_key="task.id")
    timesheet_id: int | None = Field(default=None, foreign_key="timesheet.id")
    task: Optional["Task"] = Relationship(back_populates="worklogs")
    timesheet: Optional["Timesheet"] = Relationship(back_populates="worklogs")


class Timesheet(SQLModel, table=True):
    """工时表实体。

    按员工与周期汇总多个工时记录，用于周度或月度的人力投入统计。
    """

    id: int | None = Field(default=None, primary_key=True)
    week_label: str
    employee_id: int = Field(foreign_key="employee.id")
    employee: Optional["Employee"] = Relationship(back_populates="timesheets")
    worklogs: list["Worklog"] = Relationship(back_populates="timesheet")


class Ceremony(SQLModel, table=True):
    """敏捷会议实体。

    表示团队例会、评审或回顾等活动安排，连接团队、迭代与会议室资源。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int = Field(foreign_key="team.id")
    sprint_id: int | None = Field(default=None, foreign_key="sprint.id")
    room_id: int | None = Field(default=None, foreign_key="room.id")
    team: Optional["Team"] = Relationship(back_populates="ceremonies")
    sprint: Optional["Sprint"] = Relationship(back_populates="ceremonies")
    room: Optional["Room"] = Relationship(back_populates="ceremonies")


class AutomationRule(SQLModel, table=True):
    """自动化规则实体。

    表示工作区内的流程自动执行配置，用于在特定条件下自动驱动协作流程。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    workspace_id: int = Field(foreign_key="workspace.id")
    workspace: Optional["Workspace"] = Relationship(back_populates="automations")


class KnowledgeArticle(SQLModel, table=True):
    """知识文章实体。

    表示由员工撰写和维护的内部知识内容，是组织沉淀经验与规范的载体。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int | None = Field(default=None, foreign_key="employee.id")
    author: Optional["Employee"] = Relationship(back_populates="knowledge_articles")


class Notification(SQLModel, table=True):
    """通知实体。

    表示发送给员工的站内提醒消息，用于同步审批、任务或系统状态变更。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    recipient_id: int = Field(foreign_key="employee.id")
    recipient: Optional["Employee"] = Relationship(back_populates="notifications")
