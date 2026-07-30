from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.enterprise_voyager.models import (
    Approval,
    Asset,
    Attachment,
    AutomationRule,
    Calendar,
    CalendarEvent,
    Ceremony,
    Checklist,
    ChecklistItem,
    Comment,
    Contract,
    Dashboard,
    Department,
    Dependency,
    Document,
    DocumentRevision,
    Employee,
    Epic,
    Invoice,
    KnowledgeArticle,
    Label,
    Milestone,
    Notification,
    Office,
    Organization,
    Project,
    Risk,
    Room,
    Sprint,
    Story,
    Task,
    TaskLabel,
    Team,
    Timesheet,
    Vendor,
    Widget,
    Worklog,
    Workspace,
)

engine = create_async_engine("sqlite+aiosqlite:///enterprise_voyager_demo.db", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


ALL_ENTITIES = [
    Organization, Workspace, Department, Office, Team, Employee,
    Project, Epic, Story, Sprint, Task, Comment, Checklist, ChecklistItem,
    Attachment, Label, TaskLabel, Milestone, Dependency, Approval, Worklog,
    Timesheet, Ceremony, Room, Calendar, CalendarEvent, Document,
    DocumentRevision, Dashboard, Widget, Notification, Vendor, Contract,
    Invoice, Asset, Risk, AutomationRule, KnowledgeArticle,
]


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with async_session() as session:
        existing = await session.exec(select(Organization))
        if existing.first():
            return

        org = Organization(name="Acme Enterprise")
        session.add(org)
        await session.commit()
        await session.refresh(org)

        workspaces = [Workspace(name="Platform", organization_id=org.id), Workspace(name="Operations", organization_id=org.id)]
        departments = [Department(name="Engineering", organization_id=org.id), Department(name="Finance", organization_id=org.id), Department(name="HR", organization_id=org.id)]
        offices = [Office(city="Shanghai", country="CN", organization_id=org.id), Office(city="Singapore", country="SG", organization_id=org.id)]
        vendors = [Vendor(name="CloudCo", organization_id=org.id), Vendor(name="DeviceHub", organization_id=org.id)]
        session.add_all(workspaces + departments + offices + vendors)
        await session.commit()
        for item in workspaces + departments + offices + vendors:
            await session.refresh(item)

        teams = [
            Team(name="Backend", workspace_id=workspaces[0].id, department_id=departments[0].id),
            Team(name="Frontend", workspace_id=workspaces[0].id, department_id=departments[0].id),
            Team(name="PMO", workspace_id=workspaces[1].id, department_id=departments[1].id),
        ]
        session.add_all(teams)
        await session.commit()
        for item in teams:
            await session.refresh(item)

        employees = [
            Employee(full_name="Alice Chen", email="alice@acme.io", department_id=departments[0].id, office_id=offices[0].id, team_id=teams[0].id),
            Employee(full_name="Bob Lin", email="bob@acme.io", department_id=departments[0].id, office_id=offices[0].id, team_id=teams[1].id),
            Employee(full_name="Cathy Wu", email="cathy@acme.io", department_id=departments[1].id, office_id=offices[1].id, team_id=teams[2].id),
            Employee(full_name="David Tan", email="david@acme.io", department_id=departments[2].id, office_id=offices[1].id),
            Employee(full_name="Eva Sun", email="eva@acme.io", department_id=departments[0].id, office_id=offices[0].id, team_id=teams[0].id),
            Employee(full_name="Frank Gao", email="frank@acme.io", department_id=departments[0].id, office_id=offices[1].id, team_id=teams[1].id),
        ]
        session.add_all(employees)
        await session.commit()
        for item in employees:
            await session.refresh(item)
        employees[1].manager_id = employees[0].id
        employees[4].manager_id = employees[0].id
        employees[5].manager_id = employees[1].id
        await session.commit()

        rooms = [Room(name="Pearl", office_id=offices[0].id), Room(name="Marina", office_id=offices[1].id)]
        dashboards = [Dashboard(title="Exec Overview", workspace_id=workspaces[0].id), Dashboard(title="Ops Health", workspace_id=workspaces[1].id)]
        automations = [AutomationRule(name="Escalate blockers", workspace_id=workspaces[0].id), AutomationRule(name="Invoice reminder", workspace_id=workspaces[1].id)]
        calendars = [Calendar(title="Alice Calendar", owner_id=employees[0].id), Calendar(title="Pearl Room", room_id=1)]
        session.add_all(rooms + dashboards + automations + calendars)
        await session.commit()
        for item in rooms + dashboards + automations + calendars:
            await session.refresh(item)

        projects = [
            Project(name="Unified Portal", workspace_id=workspaces[0].id, team_id=teams[0].id),
            Project(name="Billing Revamp", workspace_id=workspaces[1].id, team_id=teams[2].id),
            Project(name="Employee Hub", workspace_id=workspaces[0].id, team_id=teams[1].id),
        ]
        session.add_all(projects)
        await session.commit()
        for item in projects:
            await session.refresh(item)

        epics = [Epic(title="Identity", project_id=projects[0].id), Epic(title="Payments", project_id=projects[1].id), Epic(title="Onboarding", project_id=projects[2].id)]
        session.add_all(epics)
        await session.commit()
        for item in epics:
            await session.refresh(item)

        stories = [Story(title="SSO login", epic_id=epics[0].id), Story(title="Invoice workflow", epic_id=epics[1].id), Story(title="HR checklist", epic_id=epics[2].id)]
        sprints = [Sprint(name="Portal Sprint 1", project_id=projects[0].id), Sprint(name="Billing Sprint 1", project_id=projects[1].id), Sprint(name="Hub Sprint 1", project_id=projects[2].id)]
        milestones = [Milestone(title="Portal Beta", project_id=projects[0].id), Milestone(title="Finance GoLive", project_id=projects[1].id)]
        docs = [Document(title="Portal ADR", project_id=projects[0].id), Document(title="Billing SOP", project_id=projects[1].id)]
        contracts = [Contract(code="CC-2026-01", vendor_id=vendors[0].id), Contract(code="DH-2026-02", vendor_id=vendors[1].id)]
        labels = [Label(name="backend", color="#3498db"), Label(name="urgent", color="#e74c3c"), Label(name="finance", color="#2ecc71")]
        notifications = [Notification(title="Task assigned", recipient_id=employees[0].id), Notification(title="Approval pending", recipient_id=employees[2].id)]
        articles = [KnowledgeArticle(title="Runbook: SSO incident", author_id=employees[0].id), KnowledgeArticle(title="How to approve invoice", author_id=employees[2].id)]
        session.add_all(stories + sprints + milestones + docs + contracts + labels + notifications + articles)
        await session.commit()
        for item in stories + sprints + milestones + docs + contracts + labels + articles:
            await session.refresh(item)

        tasks = [
            Task(title="Design identity schema", sprint_id=sprints[0].id, story_id=stories[0].id, assignee_id=employees[0].id, creator_id=employees[2].id),
            Task(title="Implement SSO callback", sprint_id=sprints[0].id, story_id=stories[0].id, assignee_id=employees[4].id, creator_id=employees[0].id),
            Task(title="Map invoice states", sprint_id=sprints[1].id, story_id=stories[1].id, assignee_id=employees[2].id, creator_id=employees[2].id),
            Task(title="Automate HR onboarding", sprint_id=sprints[2].id, story_id=stories[2].id, assignee_id=employees[3].id, creator_id=employees[1].id),
            Task(title="Build employee dashboard", sprint_id=sprints[2].id, story_id=stories[2].id, assignee_id=employees[1].id, creator_id=employees[3].id),
        ]
        session.add_all(tasks)
        await session.commit()
        for item in tasks:
            await session.refresh(item)
        tasks[1].parent_task_id = tasks[0].id
        await session.commit()

        session.add_all([
            Comment(body="Need audit fields", task_id=tasks[0].id, author_id=employees[1].id),
            Comment(body="Callback flow approved", task_id=tasks[1].id, author_id=employees[0].id),
            Checklist(title="Release checklist", task_id=tasks[1].id),
            Checklist(title="Invoice review checklist", task_id=tasks[2].id),
            Attachment(file_name="adr.md", task_id=tasks[0].id, document_id=docs[0].id),
            Attachment(file_name="sop.pdf", task_id=tasks[2].id, document_id=docs[1].id),
            TaskLabel(task_id=tasks[0].id, label_id=labels[0].id),
            TaskLabel(task_id=tasks[2].id, label_id=labels[2].id),
            TaskLabel(task_id=tasks[2].id, label_id=labels[1].id),
            Dependency(blocked_task_id=tasks[1].id, blocking_task_id=tasks[0].id),
            Approval(task_id=tasks[2].id, approver_id=employees[2].id, status="approved"),
            Timesheet(week_label="2026-W27", employee_id=employees[0].id),
            Timesheet(week_label="2026-W27", employee_id=employees[2].id),
            Ceremony(name="Sprint planning", team_id=teams[0].id, sprint_id=sprints[0].id, room_id=rooms[0].id),
            Ceremony(name="Finance standup", team_id=teams[2].id, sprint_id=sprints[1].id, room_id=rooms[1].id),
            CalendarEvent(title="Portal planning", calendar_id=calendars[0].id),
            CalendarEvent(title="Room booking", calendar_id=calendars[1].id),
            DocumentRevision(version="v1", document_id=docs[0].id),
            DocumentRevision(version="v2", document_id=docs[0].id),
            Widget(title="Burnup", dashboard_id=dashboards[0].id),
            Widget(title="Cashflow", dashboard_id=dashboards[1].id),
            Invoice(amount=120000, contract_id=contracts[0].id, project_id=projects[0].id),
            Invoice(amount=80000, contract_id=contracts[1].id, project_id=projects[1].id),
            Asset(name="MacBook Pro", owner_id=employees[0].id, vendor_id=vendors[1].id),
            Asset(name="AWS account", owner_id=employees[2].id, vendor_id=vendors[0].id),
            Risk(title="SSO vendor delay", project_id=projects[0].id, task_id=tasks[1].id),
            Risk(title="Invoice compliance", project_id=projects[1].id, task_id=tasks[2].id),
            Worklog(hours=6.5, task_id=tasks[0].id, timesheet_id=1),
            Worklog(hours=4.0, task_id=tasks[2].id, timesheet_id=2),
        ])
        await session.commit()

        checklist_items = [
            ChecklistItem(title="Security review", checklist_id=1, done=True),
            ChecklistItem(title="Rollback plan", checklist_id=1, done=False),
            ChecklistItem(title="Legal approval", checklist_id=2, done=True),
        ]
        session.add_all(checklist_items)
        await session.commit()
