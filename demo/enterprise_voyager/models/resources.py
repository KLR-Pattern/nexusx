from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx import Relationship as CustomRelationship


class Calendar(SQLModel, table=True):
    """日历实体。

    表示员工或会议室维度的日程容器，用于组织多个 `CalendarEvent`。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    room_id: int | None = Field(default=None, foreign_key="room.id")
    owner: Optional["Employee"] = Relationship(back_populates="calendars")
    room: Optional["Room"] = Relationship(back_populates="calendars")
    events: list["CalendarEvent"] = Relationship(back_populates="calendar")


class CalendarEvent(SQLModel, table=True):
    """日历事件实体。

    表示某个日历中的单次事件安排，是会议、提醒或占用时段的具体记录。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    calendar_id: int = Field(foreign_key="calendar.id")
    calendar: Optional["Calendar"] = Relationship(back_populates="events")


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
    project: Optional["Project"] = Relationship(back_populates="documents")
    attachments: list["Attachment"] = Relationship(back_populates="document")
    revisions: list["DocumentRevision"] = Relationship(back_populates="document")


class DocumentRevision(SQLModel, table=True):
    """文档版本实体。

    表示文档随时间演进的版本快照，用于追踪知识内容的历史变更。
    """

    id: int | None = Field(default=None, primary_key=True)
    version: str
    document_id: int = Field(foreign_key="document.id")
    document: Optional["Document"] = Relationship(back_populates="revisions")


class Dashboard(SQLModel, table=True):
    """仪表盘实体。

    表示工作区下聚合展示指标的小面板集合，用于集中观察项目或团队状态。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    workspace_id: int = Field(foreign_key="workspace.id")
    workspace: Optional["Workspace"] = Relationship(back_populates="dashboards")
    widgets: list["Widget"] = Relationship(back_populates="dashboard")


class Widget(SQLModel, table=True):
    """组件实体。

    表示仪表盘中的单个可视化卡片，是指标、图表或摘要信息的最小展示单元。
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    dashboard_id: int = Field(foreign_key="dashboard.id")
    dashboard: Optional["Dashboard"] = Relationship(back_populates="widgets")
