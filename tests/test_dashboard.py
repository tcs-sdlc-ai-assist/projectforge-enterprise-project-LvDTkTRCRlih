import uuid
from datetime import date, datetime, timedelta

import pytest
import httpx

from main import app
from database import engine, Base, async_session_factory
from models.user import User
from models.department import Department
from models.project import Project
from models.sprint import Sprint
from models.ticket import Ticket
from models.time_entry import TimeEntry
from dependencies import create_session_cookie, serializer

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _make_session_cookie(user_id: str) -> str:
    return serializer.dumps({"user_id": user_id})


async def _create_user(
    session,
    username: str,
    role: str = "developer",
    is_active: bool = True,
) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=pwd_context.hash("testpassword123"),
        email=f"{username}@test.com",
        first_name=username.capitalize(),
        last_name="User",
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_department(session, name: str = "Engineering") -> Department:
    dept = Department(
        id=str(uuid.uuid4()),
        name=name,
        description=f"{name} department",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(dept)
    await session.flush()
    return dept


async def _create_project(
    session,
    name: str,
    key: str,
    owner_id: str,
    department_id: str | None = None,
    status: str = "active",
) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name=name,
        key=key,
        description=f"{name} project",
        department_id=department_id,
        owner_id=owner_id,
        status=status,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(project)
    await session.flush()
    return project


async def _create_sprint(
    session,
    project_id: str,
    name: str,
    status: str = "active",
    start_date: date | None = None,
    end_date: date | None = None,
) -> Sprint:
    sprint = Sprint(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=name,
        status=status,
        start_date=start_date or date.today(),
        end_date=end_date or (date.today() + timedelta(days=14)),
    )
    session.add(sprint)
    await session.flush()
    return sprint


async def _create_ticket(
    session,
    project_id: str,
    reporter_id: str,
    title: str,
    status: str = "backlog",
    priority: str = "medium",
    ticket_type: str = "task",
    assignee_id: str | None = None,
    sprint_id: str | None = None,
    story_points: int | None = None,
) -> Ticket:
    ticket = Ticket(
        id=str(uuid.uuid4()),
        project_id=project_id,
        reporter_id=reporter_id,
        title=title,
        status=status,
        priority=priority,
        type=ticket_type,
        assignee_id=assignee_id,
        sprint_id=sprint_id,
        story_points=story_points,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def _create_time_entry(
    session,
    ticket_id: str,
    user_id: str,
    hours: float,
    entry_date: date | None = None,
    billable: bool = False,
) -> TimeEntry:
    entry = TimeEntry(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        user_id=user_id,
        hours=hours,
        date=entry_date or date.today(),
        billable=billable,
        created_at=datetime.utcnow(),
    )
    session.add(entry)
    await session.flush()
    return entry


@pytest.mark.asyncio
async def test_dashboard_requires_authentication():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_accessible_by_super_admin():
    async with async_session_factory() as session:
        admin = await _create_user(session, "superadmin", role="super_admin")
        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        assert "Analytics Dashboard" in response.text


@pytest.mark.asyncio
async def test_dashboard_accessible_by_project_manager():
    async with async_session_factory() as session:
        pm = await _create_user(session, "projmanager", role="project_manager")
        await session.commit()
        pm_id = pm.id

    cookie = _make_session_cookie(pm_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        assert "Analytics Dashboard" in response.text


@pytest.mark.asyncio
async def test_dashboard_accessible_by_developer():
    async with async_session_factory() as session:
        dev = await _create_user(session, "devuser", role="developer")
        await session.commit()
        dev_id = dev.id

    cookie = _make_session_cookie(dev_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        assert "Analytics Dashboard" in response.text


@pytest.mark.asyncio
async def test_dashboard_accessible_by_team_lead():
    async with async_session_factory() as session:
        tl = await _create_user(session, "teamlead", role="team_lead")
        await session.commit()
        tl_id = tl.id

    cookie = _make_session_cookie(tl_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        assert "Analytics Dashboard" in response.text


@pytest.mark.asyncio
async def test_dashboard_denied_for_inactive_user():
    async with async_session_factory() as session:
        inactive = await _create_user(
            session, "inactiveuser", role="super_admin", is_active=False
        )
        await session.commit()
        inactive_id = inactive.id

    cookie = _make_session_cookie(inactive_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_summary_cards_empty_state():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_empty", role="super_admin")
        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text
        assert "Total Projects" in text
        assert "Active Sprints" in text
        assert "Open Tickets" in text
        assert "Overdue Tickets" in text
        assert "Hours Logged" in text


@pytest.mark.asyncio
async def test_dashboard_summary_cards_with_data():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_data", role="super_admin")
        dept = await _create_department(session, "TestDept")

        project1 = await _create_project(
            session, "Project Alpha", "ALPHA", admin.id, dept.id, status="active"
        )
        project2 = await _create_project(
            session, "Project Beta", "BETA", admin.id, dept.id, status="planning"
        )

        sprint_active = await _create_sprint(
            session, project1.id, "Sprint 1", status="active"
        )
        await _create_sprint(
            session, project1.id, "Sprint 2", status="planning"
        )

        await _create_ticket(
            session, project1.id, admin.id, "Ticket 1",
            status="backlog", sprint_id=sprint_active.id,
        )
        await _create_ticket(
            session, project1.id, admin.id, "Ticket 2",
            status="in_progress", sprint_id=sprint_active.id,
        )
        await _create_ticket(
            session, project1.id, admin.id, "Ticket 3",
            status="done",
        )
        ticket4 = await _create_ticket(
            session, project2.id, admin.id, "Ticket 4",
            status="todo",
        )

        await _create_time_entry(session, ticket4.id, admin.id, 2.5)
        await _create_time_entry(session, ticket4.id, admin.id, 1.5, billable=True)

        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Total Projects" in text
        assert "Active Sprints" in text
        assert "Open Tickets" in text
        assert "Hours Logged" in text


@pytest.mark.asyncio
async def test_dashboard_ticket_status_distribution():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_dist", role="super_admin")
        project = await _create_project(
            session, "DistProject", "DIST", admin.id, status="active"
        )

        await _create_ticket(
            session, project.id, admin.id, "Backlog 1", status="backlog"
        )
        await _create_ticket(
            session, project.id, admin.id, "Backlog 2", status="backlog"
        )
        await _create_ticket(
            session, project.id, admin.id, "Todo 1", status="todo"
        )
        await _create_ticket(
            session, project.id, admin.id, "InProgress 1", status="in_progress"
        )
        await _create_ticket(
            session, project.id, admin.id, "Done 1", status="done"
        )
        await _create_ticket(
            session, project.id, admin.id, "Done 2", status="done"
        )
        await _create_ticket(
            session, project.id, admin.id, "Done 3", status="done"
        )

        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Ticket Status Distribution" in text
        assert "Backlog" in text or "backlog" in text


@pytest.mark.asyncio
async def test_dashboard_project_health_overview():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_health", role="super_admin")
        project = await _create_project(
            session, "HealthProject", "HLTH", admin.id, status="active"
        )

        await _create_ticket(
            session, project.id, admin.id, "Open Ticket", status="in_progress"
        )
        await _create_ticket(
            session, project.id, admin.id, "Done Ticket", status="done"
        )

        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Project Health Overview" in text
        assert "HealthProject" in text


@pytest.mark.asyncio
async def test_dashboard_recent_activity_section():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_activity", role="super_admin")
        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Recent Activity" in text


@pytest.mark.asyncio
async def test_dashboard_quick_actions_visible_for_admin():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_qa", role="super_admin")
        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Quick Actions" in text
        assert "New Project" in text
        assert "Manage Users" in text
        assert "Audit Log" in text


@pytest.mark.asyncio
async def test_dashboard_quick_actions_visible_for_project_manager():
    async with async_session_factory() as session:
        pm = await _create_user(session, "pm_qa", role="project_manager")
        await session.commit()
        pm_id = pm.id

    cookie = _make_session_cookie(pm_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Quick Actions" in text
        assert "New Project" in text
        assert "Manage Users" not in text


@pytest.mark.asyncio
async def test_dashboard_quick_actions_hidden_for_developer():
    async with async_session_factory() as session:
        dev = await _create_user(session, "dev_qa", role="developer")
        await session.commit()
        dev_id = dev.id

    cookie = _make_session_cookie(dev_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Quick Actions" not in text


@pytest.mark.asyncio
async def test_dashboard_overdue_tickets_count():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_overdue", role="super_admin")
        project = await _create_project(
            session, "OverdueProject", "OVRD", admin.id, status="active"
        )

        overdue_sprint = await _create_sprint(
            session,
            project.id,
            "Overdue Sprint",
            status="active",
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() - timedelta(days=1),
        )

        await _create_ticket(
            session, project.id, admin.id, "Overdue Ticket 1",
            status="in_progress", sprint_id=overdue_sprint.id,
        )
        await _create_ticket(
            session, project.id, admin.id, "Overdue Ticket 2",
            status="todo", sprint_id=overdue_sprint.id,
        )
        await _create_ticket(
            session, project.id, admin.id, "Done Ticket",
            status="done", sprint_id=overdue_sprint.id,
        )

        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Overdue Tickets" in text
        assert "Needs attention" in text


@pytest.mark.asyncio
async def test_dashboard_hours_logged_accuracy():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_hours", role="super_admin")
        project = await _create_project(
            session, "HoursProject", "HRS", admin.id, status="active"
        )
        ticket = await _create_ticket(
            session, project.id, admin.id, "Hours Ticket", status="in_progress"
        )

        await _create_time_entry(session, ticket.id, admin.id, 3.5)
        await _create_time_entry(session, ticket.id, admin.id, 2.0)
        await _create_time_entry(session, ticket.id, admin.id, 1.5)

        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Hours Logged" in text
        assert "7.0" in text


@pytest.mark.asyncio
async def test_dashboard_invalid_session_cookie():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": "invalid-cookie-value"},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_nonexistent_user_session():
    fake_user_id = str(uuid.uuid4())
    cookie = _make_session_cookie(fake_user_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_multiple_projects_displayed():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_multi", role="super_admin")

        for i in range(5):
            await _create_project(
                session,
                f"MultiProject {i}",
                f"MP{i}",
                admin.id,
                status="active" if i % 2 == 0 else "planning",
            )

        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        for i in range(5):
            assert f"MultiProject {i}" in text


@pytest.mark.asyncio
async def test_dashboard_active_sprints_count():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_sprints", role="super_admin")
        project = await _create_project(
            session, "SprintProject", "SPRT", admin.id, status="active"
        )

        await _create_sprint(session, project.id, "Active Sprint 1", status="active")
        await _create_sprint(session, project.id, "Planning Sprint", status="planning")
        await _create_sprint(session, project.id, "Completed Sprint", status="completed")

        project2 = await _create_project(
            session, "SprintProject2", "SPR2", admin.id, status="active"
        )
        await _create_sprint(session, project2.id, "Active Sprint 2", status="active")

        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "Active Sprints" in text
        assert "2 currently running" in text


@pytest.mark.asyncio
async def test_dashboard_no_projects_shows_empty_state():
    async with async_session_factory() as session:
        admin = await _create_user(session, "admin_noproj", role="super_admin")
        await session.commit()
        admin_id = admin.id

    cookie = _make_session_cookie(admin_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 200
        text = response.text

        assert "No projects yet" in text or "No ticket data available" in text