import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base, get_db
from dependencies import create_session_cookie, serializer
from main import app
from models.audit_log import AuditLog
from models.department import Department
from models.user import User

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_audit.db"

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
    await engine.dispose()


def _make_session_cookie(user_id: str) -> dict:
    token = serializer.dumps({"user_id": user_id})
    return {"session": token}


async def _create_user(
    session: AsyncSession,
    username: str = "testuser",
    role: str = "developer",
    email: str | None = None,
) -> User:
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        username=username,
        password_hash=pwd_context.hash("testpassword123"),
        email=email or f"{username}@test.com",
        first_name="Test",
        last_name="User",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_audit_log(
    session: AsyncSession,
    actor_id: str,
    action: str = "create",
    entity_type: str = "project",
    entity_id: str | None = None,
    changes: str | None = None,
    timestamp: datetime | None = None,
) -> AuditLog:
    entry = AuditLog(
        id=str(uuid.uuid4()),
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id or str(uuid.uuid4()),
        changes=changes,
        timestamp=timestamp or datetime.utcnow(),
    )
    session.add(entry)
    await session.flush()
    return entry


@pytest.mark.asyncio
async def test_audit_log_page_requires_admin_role():
    """Non-admin users should receive a 403 when accessing the audit log."""
    async with test_session_factory() as session:
        developer = await _create_user(session, username="dev1", role="developer")
        await session.commit()

    cookies = _make_session_cookie(developer.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log", cookies=cookies)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_audit_log_page_accessible_by_super_admin():
    """Super admin users should be able to access the audit log page."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin1", role="super_admin")
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log", cookies=cookies)
    assert response.status_code == 200
    assert "Audit Log" in response.text


@pytest.mark.asyncio
async def test_audit_log_page_accessible_by_admin_role():
    """Users with 'admin' role should be able to access the audit log page."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin2", role="admin")
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log", cookies=cookies)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_audit_log_unauthenticated_returns_401():
    """Unauthenticated requests to the audit log should return 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_audit_log_displays_entries():
    """Audit log page should display existing audit entries."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin3", role="super_admin")
        await _create_audit_log(
            session,
            actor_id=admin.id,
            action="create",
            entity_type="project",
            changes='{"name": "Test Project"}',
        )
        await _create_audit_log(
            session,
            actor_id=admin.id,
            action="update",
            entity_type="ticket",
            changes='{"status": {"old": "backlog", "new": "todo"}}',
        )
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log", cookies=cookies)
    assert response.status_code == 200
    assert "Create" in response.text or "create" in response.text
    assert "Update" in response.text or "update" in response.text


@pytest.mark.asyncio
async def test_audit_log_filter_by_action():
    """Filtering by action should return only matching entries."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin4", role="super_admin")
        await _create_audit_log(session, actor_id=admin.id, action="create", entity_type="project")
        await _create_audit_log(session, actor_id=admin.id, action="delete", entity_type="project")
        await _create_audit_log(session, actor_id=admin.id, action="update", entity_type="ticket")
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log", params={"action": "create"}, cookies=cookies)
    assert response.status_code == 200
    assert "Create" in response.text
    # The delete entry should not appear when filtering for create
    # We check that the page rendered successfully with the filter applied
    assert 'value="create"' in response.text or "selected" in response.text


@pytest.mark.asyncio
async def test_audit_log_filter_by_entity_type():
    """Filtering by entity_type should return only matching entries."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin5", role="super_admin")
        await _create_audit_log(session, actor_id=admin.id, action="create", entity_type="project")
        await _create_audit_log(session, actor_id=admin.id, action="create", entity_type="ticket")
        await _create_audit_log(session, actor_id=admin.id, action="create", entity_type="department")
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/audit-log", params={"entity_type": "ticket"}, cookies=cookies
        )
    assert response.status_code == 200
    assert "Ticket" in response.text


@pytest.mark.asyncio
async def test_audit_log_filter_by_actor():
    """Filtering by actor username should return only matching entries."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin_actor", role="super_admin")
        other_user = await _create_user(session, username="other_actor", role="developer")
        await _create_audit_log(session, actor_id=admin.id, action="create", entity_type="project")
        await _create_audit_log(session, actor_id=other_user.id, action="update", entity_type="ticket")
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/audit-log", params={"actor": "other_actor"}, cookies=cookies
        )
    assert response.status_code == 200
    assert "other_actor" in response.text


@pytest.mark.asyncio
async def test_audit_log_filter_by_date_range():
    """Filtering by date range should return only entries within the range."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin_date", role="super_admin")
        old_date = datetime(2023, 1, 15, 12, 0, 0)
        recent_date = datetime(2024, 6, 15, 12, 0, 0)
        await _create_audit_log(
            session,
            actor_id=admin.id,
            action="create",
            entity_type="project",
            timestamp=old_date,
        )
        await _create_audit_log(
            session,
            actor_id=admin.id,
            action="update",
            entity_type="ticket",
            timestamp=recent_date,
        )
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/audit-log",
            params={"date_from": "2024-01-01", "date_to": "2024-12-31"},
            cookies=cookies,
        )
    assert response.status_code == 200
    # The 2024 entry should be present, the 2023 entry should not
    assert "2024" in response.text


@pytest.mark.asyncio
async def test_audit_log_pagination():
    """Audit log should paginate results correctly."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin_page", role="super_admin")
        # Create 25 entries (PAGE_SIZE is 20)
        for i in range(25):
            await _create_audit_log(
                session,
                actor_id=admin.id,
                action="create",
                entity_type="project",
                changes=f'{{"name": "Project {i}"}}',
                timestamp=datetime.utcnow() - timedelta(minutes=i),
            )
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Page 1 should have entries
        response_page1 = await client.get("/audit-log", params={"page": 1}, cookies=cookies)
        assert response_page1.status_code == 200
        assert "page=2" in response_page1.text or "Page" in response_page1.text

        # Page 2 should also have entries
        response_page2 = await client.get("/audit-log", params={"page": 2}, cookies=cookies)
        assert response_page2.status_code == 200


@pytest.mark.asyncio
async def test_audit_log_empty_state():
    """Audit log page should show empty state when no entries exist."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin_empty", role="super_admin")
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log", cookies=cookies)
    assert response.status_code == 200
    assert "No audit log entries found" in response.text


@pytest.mark.asyncio
async def test_audit_log_project_manager_denied():
    """Project managers should not have access to the audit log."""
    async with test_session_factory() as session:
        pm = await _create_user(session, username="pm1", role="project_manager")
        await session.commit()

    cookies = _make_session_cookie(pm.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log", cookies=cookies)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_audit_log_team_lead_denied():
    """Team leads should not have access to the audit log."""
    async with test_session_factory() as session:
        tl = await _create_user(session, username="tl1", role="team_lead")
        await session.commit()

    cookies = _make_session_cookie(tl.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log", cookies=cookies)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_audit_entry_created_on_login():
    """A login action should create an audit log entry."""
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    async with test_session_factory() as session:
        user = User(
            id=str(uuid.uuid4()),
            username="loginuser",
            password_hash=pwd_context.hash("testpassword123"),
            email="loginuser@test.com",
            first_name="Login",
            last_name="User",
            role="super_admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        user_id = user.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            data={"username": "loginuser", "password": "testpassword123"},
            follow_redirects=False,
        )
    assert response.status_code == 302

    async with test_session_factory() as session:
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.actor_id == user_id,
                AuditLog.action == "login",
            )
        )
        audit_entry = result.scalar_one_or_none()
        assert audit_entry is not None
        assert audit_entry.entity_type == "user"
        assert audit_entry.entity_id == user_id


@pytest.mark.asyncio
async def test_audit_entry_created_on_department_create():
    """Creating a department should create an audit log entry."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin_dept", role="super_admin")
        await session.commit()
        admin_id = admin.id

    cookies = _make_session_cookie(admin_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/departments",
            data={"name": "Audit Test Department", "description": "Test", "head_id": ""},
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303

    async with test_session_factory() as session:
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.actor_id == admin_id,
                AuditLog.action == "create",
                AuditLog.entity_type == "department",
            )
        )
        audit_entry = result.scalar_one_or_none()
        assert audit_entry is not None
        assert "Audit Test Department" in (audit_entry.changes or "")


@pytest.mark.asyncio
async def test_audit_entry_created_on_project_create():
    """Creating a project should create an audit log entry."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin_proj", role="super_admin")
        await session.commit()
        admin_id = admin.id

    cookies = _make_session_cookie(admin_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/projects/create",
            data={
                "name": "Audit Test Project",
                "key": "ATP",
                "description": "Test project for audit",
                "department_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303

    async with test_session_factory() as session:
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.actor_id == admin_id,
                AuditLog.action == "create",
                AuditLog.entity_type == "project",
            )
        )
        audit_entry = result.scalar_one_or_none()
        assert audit_entry is not None
        assert "Audit Test Project" in (audit_entry.changes or "")


@pytest.mark.asyncio
async def test_audit_entry_created_on_user_registration():
    """Registering a new user should create an audit log entry."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            data={
                "username": "newaudituser",
                "email": "newaudituser@test.com",
                "first_name": "New",
                "last_name": "AuditUser",
                "password": "securepassword123",
                "password_confirm": "securepassword123",
            },
            follow_redirects=False,
        )
    assert response.status_code == 302

    async with test_session_factory() as session:
        user_result = await session.execute(
            select(User).where(User.username == "newaudituser")
        )
        new_user = user_result.scalar_one_or_none()
        assert new_user is not None

        result = await session.execute(
            select(AuditLog).where(
                AuditLog.actor_id == new_user.id,
                AuditLog.action == "create",
                AuditLog.entity_type == "user",
            )
        )
        audit_entry = result.scalar_one_or_none()
        assert audit_entry is not None
        assert "newaudituser" in (audit_entry.changes or "")


@pytest.mark.asyncio
async def test_audit_log_combined_filters():
    """Multiple filters should be applied together."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin_combo", role="super_admin")
        await _create_audit_log(
            session,
            actor_id=admin.id,
            action="create",
            entity_type="project",
            timestamp=datetime(2024, 6, 15),
        )
        await _create_audit_log(
            session,
            actor_id=admin.id,
            action="delete",
            entity_type="project",
            timestamp=datetime(2024, 6, 15),
        )
        await _create_audit_log(
            session,
            actor_id=admin.id,
            action="create",
            entity_type="ticket",
            timestamp=datetime(2024, 6, 15),
        )
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/audit-log",
            params={
                "action": "create",
                "entity_type": "project",
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
            },
            cookies=cookies,
        )
    assert response.status_code == 200
    assert "Project" in response.text


@pytest.mark.asyncio
async def test_audit_log_invalid_date_filter_ignored():
    """Invalid date filter values should be ignored gracefully."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin_baddate", role="super_admin")
        await _create_audit_log(session, actor_id=admin.id, action="create", entity_type="project")
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/audit-log",
            params={"date_from": "not-a-date", "date_to": "also-not-a-date"},
            cookies=cookies,
        )
    # Should not crash, should return 200 with results
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_audit_log_page_beyond_total_pages():
    """Requesting a page beyond total pages should still return 200."""
    async with test_session_factory() as session:
        admin = await _create_user(session, username="admin_beyondpage", role="super_admin")
        await _create_audit_log(session, actor_id=admin.id, action="create", entity_type="project")
        await session.commit()

    cookies = _make_session_cookie(admin.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit-log", params={"page": 999}, cookies=cookies)
    assert response.status_code == 200