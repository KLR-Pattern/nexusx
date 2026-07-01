from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx import Relationship as CustomRelationship


class Vendor(SQLModel, table=True):
    """供应商实体。

    表示与组织合作的外部服务或设备提供方，可关联合同与资产来源。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    organization_id: int = Field(foreign_key="organization.id")
    organization: Optional["Organization"] = Relationship(back_populates="vendors")
    contracts: list["Contract"] = Relationship(back_populates="vendor")
    assets: list["Asset"] = Relationship(back_populates="vendor")


class Contract(SQLModel, table=True):
    """合同实体。

    表示与供应商签署的业务合同记录，是发票和采购关系的上游业务对象。
    """

    id: int | None = Field(default=None, primary_key=True)
    code: str
    vendor_id: int = Field(foreign_key="vendor.id")
    vendor: Optional["Vendor"] = Relationship(back_populates="contracts")
    invoices: list["Invoice"] = Relationship(back_populates="contract")


class Invoice(SQLModel, table=True):
    """发票实体。

    表示合同或项目相关的财务结算记录，可同时连接采购与项目交付场景。
    """

    id: int | None = Field(default=None, primary_key=True)
    amount: float
    contract_id: int | None = Field(default=None, foreign_key="contract.id")
    project_id: int | None = Field(default=None, foreign_key="project.id")
    contract: Optional["Contract"] = Relationship(back_populates="invoices")
    project: Optional["Project"] = Relationship(back_populates="invoices")


class Asset(SQLModel, table=True):
    """资产实体。

    表示归属员工或供应商来源的设备资产，用于管理设备分配和来源追踪。
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str
    owner_id: int | None = Field(default=None, foreign_key="employee.id")
    vendor_id: int | None = Field(default=None, foreign_key="vendor.id")
    owner: Optional["Employee"] = Relationship(back_populates="assets")
    vendor: Optional["Vendor"] = Relationship(back_populates="assets")


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
    project: Optional["Project"] = Relationship(back_populates="risks")
    task: Optional["Task"] = Relationship(back_populates="risks")


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
    task: Optional["Task"] = Relationship(back_populates="task_labels")
    label: Optional["Label"] = Relationship(back_populates="task_labels")
