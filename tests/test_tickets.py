import uuid
from datetime import date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base, get_db
from main import app
from models.comment import Comment
from models.department import Department
from models.label import Label
from models.project import Project, project_members
from models.sprint import Sprint
from models.ticket import Ticket, ticket_labels
from models.time_entry import TimeEntry
from models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_tickets.db"

engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True)
test_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def override_get_db():
    async with test_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with test_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession):
    user = User(
        id=str(uuid.uuid4()),
        username="admin_ticket_test",
        password_hash=pwd_context.hash("password123"),
        email="admin_ticket@test.com",
        first_name="Admin",
        last_name="User",
        role="super_admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def developer_user(db_session: AsyncSession):
    user = User(
        id=str(uuid.uuid4()),
        username="dev_ticket_test",
        password_hash=pwd_context.hash("password123"),
        email="dev_ticket@test.com",
        first_name="Dev",
        last_name="User",
        role="developer",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def project(db_session: AsyncSession, admin_user: User):
    proj = Project(
        id=str(uuid.uuid4()),
        name="Test Ticket Project",
        key="TTP",
        description="Project for ticket tests",
        owner_id=admin_user.id,
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(proj)
    await db_session.flush()

    await db_session.execute(
        project_members.insert().values(
            project_id=proj.id,
            user_id=admin_user.id,
        )
    )
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


@pytest_asyncio.fixture
async def project_with_dev(
    db_session: AsyncSession, project: Project, developer_user: User
):
    await db_session.execute(
        project_members.insert().values(
            project_id=project.id,
            user_id=developer_user.id,
        )
    )
    await db_session.commit()
    return project


@pytest_asyncio.fixture
async def sprint(db_session: AsyncSession, project: Project):
    s = Sprint(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Sprint 1",
        goal="Test sprint",
        status="active",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 14),
    )
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


@pytest_asyncio.fixture
async def label(db_session: AsyncSession, project: Project):
    lbl = Label(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="bug",
        color="#ef4444",
        created_at=datetime.utcnow(),
    )
    db_session.add(lbl)
    await db_session.commit()
    await db_session.refresh(lbl)
    return lbl


@pytest_asyncio.fixture
async def ticket(db_session: AsyncSession, project: Project, admin_user: User):
    t = Ticket(
        id=str(uuid.uuid4()),
        project_id=project.id,
        title="Test Ticket",
        description="A test ticket description",
        type="task",
        priority="medium",
        status="backlog",
        story_points=3,
        reporter_id=admin_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


def _login_cookies(user: User) -> dict[str, str]:
    from dependencies import serializer

    token = serializer.dumps({"user_id": user.id})
    return {"session": token}


@pytest_asyncio.fixture
async def admin_client(admin_user: User):
    cookies = _login_cookies(admin_user)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies=cookies,
        follow_redirects=False,
    ) as client:
        yield client


@pytest_asyncio.fixture
async def dev_client(developer_user: User):
    cookies = _login_cookies(developer_user)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies=cookies,
        follow_redirects=False,
    ) as client:
        yield client


@pytest_asyncio.fixture
async def anon_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Ticket List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tickets_requires_auth(anon_client: AsyncClient, project: Project):
    resp = await anon_client.get(f"/projects/{project.id}/tickets")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_tickets_returns_200(
    admin_client: AsyncClient, project: Project, ticket: Ticket
):
    resp = await admin_client.get(f"/projects/{project.id}/tickets")
    assert resp.status_code == 200
    assert ticket.title in resp.text


@pytest.mark.asyncio
async def test_list_tickets_filter_by_status(
    admin_client: AsyncClient, project: Project, ticket: Ticket
):
    resp = await admin_client.get(
        f"/projects/{project.id}/tickets", params={"status": "backlog"}
    )
    assert resp.status_code == 200
    assert ticket.title in resp.text

    resp2 = await admin_client.get(
        f"/projects/{project.id}/tickets", params={"status": "done"}
    )
    assert resp2.status_code == 200
    assert ticket.title not in resp2.text


@pytest.mark.asyncio
async def test_global_ticket_list(admin_client: AsyncClient, ticket: Ticket):
    resp = await admin_client.get("/tickets")
    assert resp.status_code == 200
    assert ticket.title in resp.text


# ---------------------------------------------------------------------------
# Create Ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_ticket_form_returns_200(
    admin_client: AsyncClient, project: Project
):
    resp = await admin_client.get(f"/projects/{project.id}/tickets/create")
    assert resp.status_code == 200
    assert "Create" in resp.text


@pytest.mark.asyncio
async def test_create_ticket_success(
    admin_client: AsyncClient,
    project: Project,
    sprint: Sprint,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/create",
        data={
            "title": "New Feature Ticket",
            "description": "Implement the new feature",
            "ticket_type": "feature",
            "priority": "high",
            "status": "todo",
            "story_points": "5",
            "assignee_id": "",
            "sprint_id": sprint.id,
            "parent_id": "",
        },
    )
    assert resp.status_code == 303
    assert "/tickets/" in resp.headers.get("location", "")

    result = await db_session.execute(
        select(Ticket).where(Ticket.title == "New Feature Ticket")
    )
    created = result.scalar_one_or_none()
    assert created is not None
    assert created.type == "feature"
    assert created.priority == "high"
    assert created.story_points == 5
    assert created.sprint_id == sprint.id


@pytest.mark.asyncio
async def test_create_ticket_missing_title_returns_422(
    admin_client: AsyncClient, project: Project
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/create",
        data={
            "title": "",
            "description": "",
            "ticket_type": "task",
            "priority": "medium",
            "status": "backlog",
            "story_points": "",
            "assignee_id": "",
            "sprint_id": "",
            "parent_id": "",
        },
    )
    assert resp.status_code == 422
    assert "Title is required" in resp.text


@pytest.mark.asyncio
async def test_create_ticket_invalid_type_returns_422(
    admin_client: AsyncClient, project: Project
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/create",
        data={
            "title": "Bad Type Ticket",
            "description": "",
            "ticket_type": "invalid_type",
            "priority": "medium",
            "status": "backlog",
            "story_points": "",
            "assignee_id": "",
            "sprint_id": "",
            "parent_id": "",
        },
    )
    assert resp.status_code == 422
    assert "Type must be one of" in resp.text


@pytest.mark.asyncio
async def test_create_ticket_with_labels(
    admin_client: AsyncClient,
    project: Project,
    label: Label,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/create",
        data=[
            ("title", "Labeled Ticket"),
            ("description", ""),
            ("ticket_type", "bug"),
            ("priority", "high"),
            ("status", "backlog"),
            ("story_points", ""),
            ("assignee_id", ""),
            ("sprint_id", ""),
            ("parent_id", ""),
            ("labels", "bug"),
        ],
    )
    assert resp.status_code == 303

    result = await db_session.execute(
        select(Ticket).where(Ticket.title == "Labeled Ticket")
    )
    created = result.scalar_one_or_none()
    assert created is not None

    label_result = await db_session.execute(
        select(ticket_labels).where(ticket_labels.c.ticket_id == created.id)
    )
    labels = label_result.all()
    assert len(labels) == 1
    assert labels[0].label_id == label.id


# ---------------------------------------------------------------------------
# Ticket Detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_detail_returns_200(
    admin_client: AsyncClient, project: Project, ticket: Ticket
):
    resp = await admin_client.get(
        f"/projects/{project.id}/tickets/{ticket.id}"
    )
    assert resp.status_code == 200
    assert ticket.title in resp.text


@pytest.mark.asyncio
async def test_ticket_detail_not_found(
    admin_client: AsyncClient, project: Project
):
    fake_id = str(uuid.uuid4())
    resp = await admin_client.get(
        f"/projects/{project.id}/tickets/{fake_id}"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ticket_detail_global_redirect(
    admin_client: AsyncClient, project: Project, ticket: Ticket
):
    resp = await admin_client.get(f"/tickets/{ticket.id}")
    assert resp.status_code == 303
    assert f"/projects/{project.id}/tickets/{ticket.id}" in resp.headers.get(
        "location", ""
    )


# ---------------------------------------------------------------------------
# Edit Ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_ticket_form_returns_200(
    admin_client: AsyncClient, project: Project, ticket: Ticket
):
    resp = await admin_client.get(
        f"/projects/{project.id}/tickets/{ticket.id}/edit"
    )
    assert resp.status_code == 200
    assert ticket.title in resp.text


@pytest.mark.asyncio
async def test_edit_ticket_success(
    admin_client: AsyncClient,
    project: Project,
    ticket: Ticket,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/{ticket.id}/edit",
        data={
            "title": "Updated Ticket Title",
            "description": "Updated description",
            "ticket_type": "bug",
            "priority": "critical",
            "status": "in_progress",
            "story_points": "8",
            "assignee_id": "",
            "sprint_id": "",
            "parent_id": "",
        },
    )
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(Ticket).where(Ticket.id == ticket.id)
    )
    updated = result.scalar_one()
    assert updated.title == "Updated Ticket Title"
    assert updated.type == "bug"
    assert updated.priority == "critical"
    assert updated.status == "in_progress"
    assert updated.story_points == 8


@pytest.mark.asyncio
async def test_edit_ticket_empty_title_returns_422(
    admin_client: AsyncClient, project: Project, ticket: Ticket
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/{ticket.id}/edit",
        data={
            "title": "",
            "description": "",
            "ticket_type": "task",
            "priority": "medium",
            "status": "backlog",
            "story_points": "",
            "assignee_id": "",
            "sprint_id": "",
            "parent_id": "",
        },
    )
    assert resp.status_code == 422
    assert "Title is required" in resp.text


# ---------------------------------------------------------------------------
# Delete Ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_ticket_success(
    admin_client: AsyncClient,
    project: Project,
    ticket: Ticket,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/{ticket.id}/delete"
    )
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(Ticket).where(Ticket.id == ticket.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_ticket_forbidden_for_developer(
    dev_client: AsyncClient,
    project_with_dev: Project,
    ticket: Ticket,
):
    resp = await dev_client.post(
        f"/projects/{project_with_dev.id}/tickets/{ticket.id}/delete"
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_ticket_global_route(
    admin_client: AsyncClient,
    project: Project,
    ticket: Ticket,
    db_session: AsyncSession,
):
    resp = await admin_client.post(f"/tickets/{ticket.id}/delete")
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(Ticket).where(Ticket.id == ticket.id)
    )
    assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Status Transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_ticket_status_via_form(
    admin_client: AsyncClient, ticket: Ticket, db_session: AsyncSession
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/transition",
        data={"status": "in_progress"},
    )
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(Ticket).where(Ticket.id == ticket.id)
    )
    updated = result.scalar_one()
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_transition_ticket_status_invalid(
    admin_client: AsyncClient, ticket: Ticket
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/transition",
        data={"status": "nonexistent_status"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_transition_ticket_status_post_endpoint(
    admin_client: AsyncClient, ticket: Ticket, db_session: AsyncSession
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/status",
        data={"status": "todo"},
    )
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(Ticket).where(Ticket.id == ticket.id)
    )
    updated = result.scalar_one()
    assert updated.status == "todo"


@pytest.mark.asyncio
async def test_transition_ticket_status_patch_api(
    admin_client: AsyncClient,
    project: Project,
    ticket: Ticket,
    db_session: AsyncSession,
):
    resp = await admin_client.patch(
        f"/projects/{project.id}/tickets/{ticket.id}/status",
        json={"status": "done"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"

    await db_session.expire_all()
    result = await db_session.execute(
        select(Ticket).where(Ticket.id == ticket.id)
    )
    updated = result.scalar_one()
    assert updated.status == "done"


@pytest.mark.asyncio
async def test_full_status_workflow(
    admin_client: AsyncClient,
    project: Project,
    ticket: Ticket,
    db_session: AsyncSession,
):
    workflow = ["todo", "in_progress", "in_review", "done"]
    for status in workflow:
        resp = await admin_client.patch(
            f"/projects/{project.id}/tickets/{ticket.id}/status",
            json={"status": status},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == status

    await db_session.expire_all()
    result = await db_session.execute(
        select(Ticket).where(Ticket.id == ticket.id)
    )
    final = result.scalar_one()
    assert final.status == "done"


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_comment_success(
    admin_client: AsyncClient,
    ticket: Ticket,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/comments",
        data={
            "content": "This is a test comment",
            "is_internal": "",
            "parent_comment_id": "",
        },
    )
    assert resp.status_code == 303

    result = await db_session.execute(
        select(Comment).where(Comment.ticket_id == ticket.id)
    )
    comments = result.scalars().all()
    assert len(comments) == 1
    assert comments[0].content == "This is a test comment"
    assert comments[0].is_internal is False


@pytest.mark.asyncio
async def test_add_internal_comment(
    admin_client: AsyncClient,
    ticket: Ticket,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/comments",
        data={
            "content": "Internal note for team",
            "is_internal": "true",
            "parent_comment_id": "",
        },
    )
    assert resp.status_code == 303

    result = await db_session.execute(
        select(Comment).where(Comment.ticket_id == ticket.id)
    )
    comments = result.scalars().all()
    assert len(comments) == 1
    assert comments[0].is_internal is True


@pytest.mark.asyncio
async def test_add_comment_empty_content_redirects(
    admin_client: AsyncClient, ticket: Ticket, project: Project
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/comments",
        data={
            "content": "",
            "is_internal": "",
            "parent_comment_id": "",
        },
    )
    assert resp.status_code == 303
    location = resp.headers.get("location", "")
    assert f"/tickets/{ticket.id}" in location


@pytest.mark.asyncio
async def test_delete_comment_success(
    admin_client: AsyncClient,
    ticket: Ticket,
    admin_user: User,
    db_session: AsyncSession,
):
    comment = Comment(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        author_id=admin_user.id,
        content="Comment to delete",
        is_internal=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(comment)
    await db_session.commit()

    resp = await admin_client.post(
        f"/tickets/{ticket.id}/comments/{comment.id}/delete"
    )
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(Comment).where(Comment.id == comment.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_comment_forbidden_for_other_user(
    dev_client: AsyncClient,
    ticket: Ticket,
    admin_user: User,
    project_with_dev: Project,
    db_session: AsyncSession,
):
    comment = Comment(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        author_id=admin_user.id,
        content="Admin comment",
        is_internal=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(comment)
    await db_session.commit()

    resp = await dev_client.post(
        f"/tickets/{ticket.id}/comments/{comment.id}/delete"
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_add_reply_comment(
    admin_client: AsyncClient,
    ticket: Ticket,
    admin_user: User,
    db_session: AsyncSession,
):
    parent_comment = Comment(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        author_id=admin_user.id,
        content="Parent comment",
        is_internal=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(parent_comment)
    await db_session.commit()

    resp = await admin_client.post(
        f"/tickets/{ticket.id}/comments",
        data={
            "content": "Reply to parent",
            "is_internal": "",
            "parent_comment_id": parent_comment.id,
        },
    )
    assert resp.status_code == 303

    result = await db_session.execute(
        select(Comment).where(
            Comment.ticket_id == ticket.id,
            Comment.parent_id == parent_comment.id,
        )
    )
    reply = result.scalar_one_or_none()
    assert reply is not None
    assert reply.content == "Reply to parent"


# ---------------------------------------------------------------------------
# Time Entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_time_entry_success(
    admin_client: AsyncClient,
    ticket: Ticket,
    project: Project,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/time-entries",
        data={
            "hours": "2.5",
            "date": "2025-01-15",
            "description": "Worked on implementation",
            "billable": "true",
        },
    )
    assert resp.status_code == 303

    result = await db_session.execute(
        select(TimeEntry).where(TimeEntry.ticket_id == ticket.id)
    )
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].hours == 2.5
    assert entries[0].billable is True
    assert entries[0].description == "Worked on implementation"
    assert entries[0].date == date(2025, 1, 15)


@pytest.mark.asyncio
async def test_add_time_entry_missing_hours_redirects(
    admin_client: AsyncClient, ticket: Ticket, project: Project
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/time-entries",
        data={
            "hours": "",
            "date": "2025-01-15",
            "description": "",
            "billable": "",
        },
    )
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_add_time_entry_missing_date_redirects(
    admin_client: AsyncClient, ticket: Ticket, project: Project
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/time-entries",
        data={
            "hours": "1.0",
            "date": "",
            "description": "",
            "billable": "",
        },
    )
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_add_time_entry_non_billable(
    admin_client: AsyncClient,
    ticket: Ticket,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/tickets/{ticket.id}/time-entries",
        data={
            "hours": "1.0",
            "date": "2025-01-16",
            "description": "Quick fix",
            "billable": "",
        },
    )
    assert resp.status_code == 303

    result = await db_session.execute(
        select(TimeEntry).where(TimeEntry.ticket_id == ticket.id)
    )
    entry = result.scalar_one()
    assert entry.billable is False


@pytest.mark.asyncio
async def test_delete_time_entry_success(
    admin_client: AsyncClient,
    ticket: Ticket,
    admin_user: User,
    db_session: AsyncSession,
):
    entry = TimeEntry(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        user_id=admin_user.id,
        hours=1.5,
        description="Entry to delete",
        date=date(2025, 1, 10),
        billable=False,
        created_at=datetime.utcnow(),
    )
    db_session.add(entry)
    await db_session.commit()

    resp = await admin_client.post(
        f"/tickets/{ticket.id}/time-entries/{entry.id}/delete"
    )
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(TimeEntry).where(TimeEntry.id == entry.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_time_entry_forbidden_for_other_user(
    dev_client: AsyncClient,
    ticket: Ticket,
    admin_user: User,
    project_with_dev: Project,
    db_session: AsyncSession,
):
    entry = TimeEntry(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        user_id=admin_user.id,
        hours=2.0,
        description="Admin entry",
        date=date(2025, 1, 10),
        billable=False,
        created_at=datetime.utcnow(),
    )
    db_session.add(entry)
    await db_session.commit()

    resp = await dev_client.post(
        f"/tickets/{ticket.id}/time-entries/{entry.id}/delete"
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Subtask Assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_subtask(
    admin_client: AsyncClient,
    project: Project,
    ticket: Ticket,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/create",
        data={
            "title": "Subtask of main ticket",
            "description": "This is a subtask",
            "ticket_type": "task",
            "priority": "low",
            "status": "backlog",
            "story_points": "1",
            "assignee_id": "",
            "sprint_id": "",
            "parent_id": ticket.id,
        },
    )
    assert resp.status_code == 303

    result = await db_session.execute(
        select(Ticket).where(Ticket.title == "Subtask of main ticket")
    )
    subtask = result.scalar_one_or_none()
    assert subtask is not None
    assert subtask.parent_id == ticket.id


@pytest.mark.asyncio
async def test_edit_ticket_set_parent(
    admin_client: AsyncClient,
    project: Project,
    ticket: Ticket,
    admin_user: User,
    db_session: AsyncSession,
):
    child = Ticket(
        id=str(uuid.uuid4()),
        project_id=project.id,
        title="Child Ticket",
        type="task",
        priority="low",
        status="backlog",
        reporter_id=admin_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(child)
    await db_session.commit()

    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/{child.id}/edit",
        data={
            "title": "Child Ticket",
            "description": "",
            "ticket_type": "task",
            "priority": "low",
            "status": "backlog",
            "story_points": "",
            "assignee_id": "",
            "sprint_id": "",
            "parent_id": ticket.id,
        },
    )
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(Ticket).where(Ticket.id == child.id)
    )
    updated_child = result.scalar_one()
    assert updated_child.parent_id == ticket.id


# ---------------------------------------------------------------------------
# Label Assignment via Edit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_ticket_assign_labels(
    admin_client: AsyncClient,
    project: Project,
    ticket: Ticket,
    label: Label,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/{ticket.id}/edit",
        data=[
            ("title", ticket.title),
            ("description", ticket.description or ""),
            ("ticket_type", ticket.type),
            ("priority", ticket.priority),
            ("status", ticket.status),
            ("story_points", str(ticket.story_points) if ticket.story_points else ""),
            ("assignee_id", ""),
            ("sprint_id", ""),
            ("parent_id", ""),
            ("labels", "bug"),
        ],
    )
    assert resp.status_code == 303

    result = await db_session.execute(
        select(ticket_labels).where(ticket_labels.c.ticket_id == ticket.id)
    )
    labels = result.all()
    assert len(labels) == 1
    assert labels[0].label_id == label.id


@pytest.mark.asyncio
async def test_edit_ticket_remove_labels(
    admin_client: AsyncClient,
    project: Project,
    ticket: Ticket,
    label: Label,
    db_session: AsyncSession,
):
    await db_session.execute(
        ticket_labels.insert().values(
            ticket_id=ticket.id,
            label_id=label.id,
        )
    )
    await db_session.commit()

    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/{ticket.id}/edit",
        data={
            "title": ticket.title,
            "description": ticket.description or "",
            "ticket_type": ticket.type,
            "priority": ticket.priority,
            "status": ticket.status,
            "story_points": str(ticket.story_points) if ticket.story_points else "",
            "assignee_id": "",
            "sprint_id": "",
            "parent_id": "",
        },
    )
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(ticket_labels).where(ticket_labels.c.ticket_id == ticket.id)
    )
    labels = result.all()
    assert len(labels) == 0


# ---------------------------------------------------------------------------
# Assignee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_ticket_with_assignee(
    admin_client: AsyncClient,
    project_with_dev: Project,
    developer_user: User,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/projects/{project_with_dev.id}/tickets/create",
        data={
            "title": "Assigned Ticket",
            "description": "",
            "ticket_type": "task",
            "priority": "medium",
            "status": "todo",
            "story_points": "2",
            "assignee_id": developer_user.id,
            "sprint_id": "",
            "parent_id": "",
        },
    )
    assert resp.status_code == 303

    result = await db_session.execute(
        select(Ticket).where(Ticket.title == "Assigned Ticket")
    )
    created = result.scalar_one_or_none()
    assert created is not None
    assert created.assignee_id == developer_user.id


@pytest.mark.asyncio
async def test_edit_ticket_change_assignee(
    admin_client: AsyncClient,
    project_with_dev: Project,
    ticket: Ticket,
    developer_user: User,
    db_session: AsyncSession,
):
    resp = await admin_client.post(
        f"/projects/{project_with_dev.id}/tickets/{ticket.id}/edit",
        data={
            "title": ticket.title,
            "description": ticket.description or "",
            "ticket_type": ticket.type,
            "priority": ticket.priority,
            "status": ticket.status,
            "story_points": str(ticket.story_points) if ticket.story_points else "",
            "assignee_id": developer_user.id,
            "sprint_id": "",
            "parent_id": "",
        },
    )
    assert resp.status_code == 303

    await db_session.expire_all()
    result = await db_session.execute(
        select(Ticket).where(Ticket.id == ticket.id)
    )
    updated = result.scalar_one()
    assert updated.assignee_id == developer_user.id


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_not_found_on_nonexistent_project(
    admin_client: AsyncClient,
):
    fake_project_id = str(uuid.uuid4())
    resp = await admin_client.get(f"/projects/{fake_project_id}/tickets")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_ticket_story_points_out_of_range(
    admin_client: AsyncClient, project: Project
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/create",
        data={
            "title": "Out of range SP",
            "description": "",
            "ticket_type": "task",
            "priority": "medium",
            "status": "backlog",
            "story_points": "200",
            "assignee_id": "",
            "sprint_id": "",
            "parent_id": "",
        },
    )
    assert resp.status_code == 422
    assert "Story points must be between" in resp.text


@pytest.mark.asyncio
async def test_create_ticket_story_points_invalid_string(
    admin_client: AsyncClient, project: Project
):
    resp = await admin_client.post(
        f"/projects/{project.id}/tickets/create",
        data={
            "title": "Invalid SP",
            "description": "",
            "ticket_type": "task",
            "priority": "medium",
            "status": "backlog",
            "story_points": "abc",
            "assignee_id": "",
            "sprint_id": "",
            "parent_id": "",
        },
    )
    assert resp.status_code == 422
    assert "Story points must be a valid integer" in resp.text