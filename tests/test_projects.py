import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base, get_db
from dependencies import SESSION_COOKIE_NAME, serializer
from main import app
from models.department import Department
from models.project import Project, project_members
from models.user import User

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_projects.db"

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


def _make_session_cookie(user_id: str) -> str:
    return serializer.dumps({"user_id": user_id})


def _auth_cookies(user_id: str) -> dict[str, str]:
    return {SESSION_COOKIE_NAME: _make_session_cookie(user_id)}


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
async def admin_user(db_session: AsyncSession) -> User:
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        id=str(uuid.uuid4()),
        username="admin_test",
        password_hash=pwd_context.hash("password123"),
        email="admin_test@projectforge.io",
        first_name="Admin",
        last_name="Test",
        role="super_admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def pm_user(db_session: AsyncSession) -> User:
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        id=str(uuid.uuid4()),
        username="pm_test",
        password_hash=pwd_context.hash("password123"),
        email="pm_test@projectforge.io",
        first_name="PM",
        last_name="Test",
        role="project_manager",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def dev_user(db_session: AsyncSession) -> User:
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        id=str(uuid.uuid4()),
        username="dev_test",
        password_hash=pwd_context.hash("password123"),
        email="dev_test@projectforge.io",
        first_name="Dev",
        last_name="Test",
        role="developer",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def department(db_session: AsyncSession) -> Department:
    dept = Department(
        id=str(uuid.uuid4()),
        name="Engineering Test",
        description="Test department",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(dept)
    await db_session.commit()
    await db_session.refresh(dept)
    return dept


@pytest_asyncio.fixture
async def sample_project(db_session: AsyncSession, admin_user: User, department: Department) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name="Test Project",
        key="TPROJ",
        description="A test project",
        department_id=department.id,
        owner_id=admin_user.id,
        status="planning",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(project)
    await db_session.flush()
    await db_session.execute(
        project_members.insert().values(
            project_id=project.id,
            user_id=admin_user.id,
        )
    )
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Project List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_projects_authenticated(client: AsyncClient, admin_user: User):
    cookies = _auth_cookies(admin_user.id)
    response = await client.get("/projects", cookies=cookies)
    assert response.status_code == 200
    assert "Projects" in response.text


@pytest.mark.asyncio
async def test_list_projects_unauthenticated(client: AsyncClient):
    response = await client.get("/projects", follow_redirects=False)
    assert response.status_code in (401, 302, 303)


@pytest.mark.asyncio
async def test_list_projects_shows_existing_project(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.get("/projects", cookies=cookies)
    assert response.status_code == 200
    assert sample_project.name in response.text
    assert sample_project.key in response.text


@pytest.mark.asyncio
async def test_list_projects_search_filter(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.get("/projects?search=TPROJ", cookies=cookies)
    assert response.status_code == 200
    assert sample_project.name in response.text


@pytest.mark.asyncio
async def test_list_projects_status_filter(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.get("/projects?status=planning", cookies=cookies)
    assert response.status_code == 200
    assert sample_project.name in response.text

    response = await client.get("/projects?status=active", cookies=cookies)
    assert response.status_code == 200
    assert sample_project.name not in response.text


# ---------------------------------------------------------------------------
# Project Create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_project_form_admin(client: AsyncClient, admin_user: User):
    cookies = _auth_cookies(admin_user.id)
    response = await client.get("/projects/create", cookies=cookies)
    assert response.status_code == 200
    assert "Create" in response.text


@pytest.mark.asyncio
async def test_create_project_form_developer_forbidden(client: AsyncClient, dev_user: User):
    cookies = _auth_cookies(dev_user.id)
    response = await client.get("/projects/create", cookies=cookies, follow_redirects=False)
    assert response.status_code in (403, 302, 303)


@pytest.mark.asyncio
async def test_create_project_success(
    client: AsyncClient, admin_user: User, department: Department, db_session: AsyncSession
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        "/projects/create",
        data={
            "name": "New Project",
            "key": "NEWP",
            "description": "A brand new project",
            "department_id": department.id,
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    result = await db_session.execute(select(Project).where(Project.key == "NEWP"))
    project = result.scalar_one_or_none()
    assert project is not None
    assert project.name == "New Project"
    assert project.owner_id == admin_user.id
    assert project.status == "planning"


@pytest.mark.asyncio
async def test_create_project_missing_name(client: AsyncClient, admin_user: User):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        "/projects/create",
        data={
            "name": "",
            "key": "MISS",
            "description": "",
            "department_id": "",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert "required" in response.text.lower() or "error" in response.text.lower()


@pytest.mark.asyncio
async def test_create_project_missing_key(client: AsyncClient, admin_user: User):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        "/projects/create",
        data={
            "name": "No Key Project",
            "key": "",
            "description": "",
            "department_id": "",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (200, 422)


@pytest.mark.asyncio
async def test_create_project_duplicate_key(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        "/projects/create",
        data={
            "name": "Duplicate Key Project",
            "key": sample_project.key,
            "description": "",
            "department_id": "",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (200, 422)
    if response.status_code == 200:
        assert "already" in response.text.lower() or "error" in response.text.lower()


@pytest.mark.asyncio
async def test_create_project_pm_allowed(
    client: AsyncClient, pm_user: User, db_session: AsyncSession
):
    cookies = _auth_cookies(pm_user.id)
    response = await client.post(
        "/projects/create",
        data={
            "name": "PM Project",
            "key": "PMP",
            "description": "Created by PM",
            "department_id": "",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    result = await db_session.execute(select(Project).where(Project.key == "PMP"))
    project = result.scalar_one_or_none()
    assert project is not None


@pytest.mark.asyncio
async def test_create_project_developer_forbidden(client: AsyncClient, dev_user: User):
    cookies = _auth_cookies(dev_user.id)
    response = await client.post(
        "/projects/create",
        data={
            "name": "Dev Project",
            "key": "DEVP",
            "description": "",
            "department_id": "",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


# ---------------------------------------------------------------------------
# Project Detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_detail_success(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.get(f"/projects/{sample_project.id}", cookies=cookies)
    assert response.status_code == 200
    assert sample_project.name in response.text
    assert sample_project.key in response.text


@pytest.mark.asyncio
async def test_project_detail_not_found(client: AsyncClient, admin_user: User):
    cookies = _auth_cookies(admin_user.id)
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/projects/{fake_id}", cookies=cookies)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Project Edit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_project_form(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.get(
        f"/projects/{sample_project.id}/edit", cookies=cookies
    )
    assert response.status_code == 200
    assert sample_project.name in response.text


@pytest.mark.asyncio
async def test_edit_project_success(
    client: AsyncClient, admin_user: User, sample_project: Project, db_session: AsyncSession
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/edit",
        data={
            "name": "Updated Project Name",
            "key": sample_project.key,
            "description": "Updated description",
            "department_id": "",
            "status": "active",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    await db_session.expire_all()
    result = await db_session.execute(
        select(Project).where(Project.id == sample_project.id)
    )
    project = result.scalar_one_or_none()
    assert project is not None
    assert project.name == "Updated Project Name"
    assert project.status == "active"


@pytest.mark.asyncio
async def test_edit_project_developer_forbidden(
    client: AsyncClient, dev_user: User, sample_project: Project
):
    cookies = _auth_cookies(dev_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/edit",
        data={
            "name": "Hacked Name",
            "key": sample_project.key,
            "description": "",
            "department_id": "",
            "status": "active",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


@pytest.mark.asyncio
async def test_edit_project_invalid_status(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/edit",
        data={
            "name": sample_project.name,
            "key": sample_project.key,
            "description": "",
            "department_id": "",
            "status": "invalid_status",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (200, 422)


# ---------------------------------------------------------------------------
# Project Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_project_admin(
    client: AsyncClient, admin_user: User, sample_project: Project, db_session: AsyncSession
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/delete",
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    await db_session.expire_all()
    result = await db_session.execute(
        select(Project).where(Project.id == sample_project.id)
    )
    project = result.scalar_one_or_none()
    assert project is None


@pytest.mark.asyncio
async def test_delete_project_pm_forbidden(
    client: AsyncClient, pm_user: User, sample_project: Project
):
    cookies = _auth_cookies(pm_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/delete",
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


@pytest.mark.asyncio
async def test_delete_project_developer_forbidden(
    client: AsyncClient, dev_user: User, sample_project: Project
):
    cookies = _auth_cookies(dev_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/delete",
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


@pytest.mark.asyncio
async def test_delete_project_not_found(client: AsyncClient, admin_user: User):
    cookies = _auth_cookies(admin_user.id)
    fake_id = str(uuid.uuid4())
    response = await client.post(
        f"/projects/{fake_id}/delete",
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Project Status Transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_transition_planning_to_active(
    client: AsyncClient, admin_user: User, sample_project: Project, db_session: AsyncSession
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/status",
        data={"status": "active"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    await db_session.expire_all()
    result = await db_session.execute(
        select(Project).where(Project.id == sample_project.id)
    )
    project = result.scalar_one()
    assert project.status == "active"


@pytest.mark.asyncio
async def test_status_transition_active_to_on_hold(
    client: AsyncClient, admin_user: User, sample_project: Project, db_session: AsyncSession
):
    sample_project.status = "active"
    db_session.add(sample_project)
    await db_session.commit()

    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/status",
        data={"status": "on_hold"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    await db_session.expire_all()
    result = await db_session.execute(
        select(Project).where(Project.id == sample_project.id)
    )
    project = result.scalar_one()
    assert project.status == "on_hold"


@pytest.mark.asyncio
async def test_status_transition_to_completed(
    client: AsyncClient, admin_user: User, sample_project: Project, db_session: AsyncSession
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/status",
        data={"status": "completed"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    await db_session.expire_all()
    result = await db_session.execute(
        select(Project).where(Project.id == sample_project.id)
    )
    project = result.scalar_one()
    assert project.status == "completed"


@pytest.mark.asyncio
async def test_status_transition_to_archived(
    client: AsyncClient, admin_user: User, sample_project: Project, db_session: AsyncSession
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/status",
        data={"status": "archived"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    await db_session.expire_all()
    result = await db_session.execute(
        select(Project).where(Project.id == sample_project.id)
    )
    project = result.scalar_one()
    assert project.status == "archived"


@pytest.mark.asyncio
async def test_status_transition_invalid_status(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/status",
        data={"status": "nonexistent"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


@pytest.mark.asyncio
async def test_status_transition_developer_forbidden(
    client: AsyncClient, dev_user: User, sample_project: Project
):
    cookies = _auth_cookies(dev_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/status",
        data={"status": "active"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


# ---------------------------------------------------------------------------
# Project Membership
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_member_to_project(
    client: AsyncClient,
    admin_user: User,
    dev_user: User,
    sample_project: Project,
    db_session: AsyncSession,
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/members/add",
        data={"user_id": dev_user.id},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    result = await db_session.execute(
        select(project_members).where(
            project_members.c.project_id == sample_project.id,
            project_members.c.user_id == dev_user.id,
        )
    )
    membership = result.first()
    assert membership is not None


@pytest.mark.asyncio
async def test_add_duplicate_member(
    client: AsyncClient,
    admin_user: User,
    sample_project: Project,
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/members/add",
        data={"user_id": admin_user.id},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


@pytest.mark.asyncio
async def test_add_member_no_user_id(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/members/add",
        data={"user_id": ""},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


@pytest.mark.asyncio
async def test_add_member_developer_forbidden(
    client: AsyncClient,
    dev_user: User,
    admin_user: User,
    sample_project: Project,
):
    cookies = _auth_cookies(dev_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/members/add",
        data={"user_id": admin_user.id},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


@pytest.mark.asyncio
async def test_remove_member_from_project(
    client: AsyncClient,
    admin_user: User,
    dev_user: User,
    sample_project: Project,
    db_session: AsyncSession,
):
    await db_session.execute(
        project_members.insert().values(
            project_id=sample_project.id,
            user_id=dev_user.id,
        )
    )
    await db_session.commit()

    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/members/remove",
        data={"user_id": dev_user.id},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    result = await db_session.execute(
        select(project_members).where(
            project_members.c.project_id == sample_project.id,
            project_members.c.user_id == dev_user.id,
        )
    )
    membership = result.first()
    assert membership is None


@pytest.mark.asyncio
async def test_remove_nonexistent_member(
    client: AsyncClient,
    admin_user: User,
    dev_user: User,
    sample_project: Project,
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/members/remove",
        data={"user_id": dev_user.id},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


@pytest.mark.asyncio
async def test_remove_member_developer_forbidden(
    client: AsyncClient,
    dev_user: User,
    admin_user: User,
    sample_project: Project,
):
    cookies = _auth_cookies(dev_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/members/remove",
        data={"user_id": admin_user.id},
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


# ---------------------------------------------------------------------------
# Kanban Board
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kanban_board_renders(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.get(
        f"/projects/{sample_project.id}/board", cookies=cookies
    )
    assert response.status_code == 200
    assert "Kanban Board" in response.text
    assert "Backlog" in response.text
    assert "To Do" in response.text
    assert "In Progress" in response.text
    assert "In Review" in response.text
    assert "Done" in response.text


@pytest.mark.asyncio
async def test_kanban_board_not_found(client: AsyncClient, admin_user: User):
    cookies = _auth_cookies(admin_user.id)
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/projects/{fake_id}/board", cookies=cookies)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_kanban_board_with_filters(
    client: AsyncClient, admin_user: User, sample_project: Project
):
    cookies = _auth_cookies(admin_user.id)
    response = await client.get(
        f"/projects/{sample_project.id}/board?assignee_id={admin_user.id}",
        cookies=cookies,
    )
    assert response.status_code == 200
    assert "Kanban Board" in response.text


# ---------------------------------------------------------------------------
# RBAC Enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_developer_can_view_projects(client: AsyncClient, dev_user: User):
    cookies = _auth_cookies(dev_user.id)
    response = await client.get("/projects", cookies=cookies)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_developer_cannot_create_project(client: AsyncClient, dev_user: User):
    cookies = _auth_cookies(dev_user.id)
    response = await client.get("/projects/create", cookies=cookies, follow_redirects=False)
    assert response.status_code in (403, 302, 303)


@pytest.mark.asyncio
async def test_developer_cannot_edit_project(
    client: AsyncClient, dev_user: User, sample_project: Project
):
    cookies = _auth_cookies(dev_user.id)
    response = await client.get(
        f"/projects/{sample_project.id}/edit",
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


@pytest.mark.asyncio
async def test_developer_cannot_delete_project(
    client: AsyncClient, dev_user: User, sample_project: Project
):
    cookies = _auth_cookies(dev_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/delete",
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


@pytest.mark.asyncio
async def test_pm_can_create_project(client: AsyncClient, pm_user: User):
    cookies = _auth_cookies(pm_user.id)
    response = await client.get("/projects/create", cookies=cookies)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_pm_can_edit_project(
    client: AsyncClient, pm_user: User, sample_project: Project
):
    cookies = _auth_cookies(pm_user.id)
    response = await client.get(
        f"/projects/{sample_project.id}/edit", cookies=cookies
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_pm_cannot_delete_project(
    client: AsyncClient, pm_user: User, sample_project: Project
):
    cookies = _auth_cookies(pm_user.id)
    response = await client.post(
        f"/projects/{sample_project.id}/delete",
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code in (403, 302, 303)


@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_create(client: AsyncClient):
    response = await client.get("/projects/create", follow_redirects=False)
    assert response.status_code in (401, 302, 303)


@pytest.mark.asyncio
async def test_unauthenticated_cannot_post_create(client: AsyncClient):
    response = await client.post(
        "/projects/create",
        data={
            "name": "Unauthorized",
            "key": "UNAUTH",
            "description": "",
            "department_id": "",
        },
        follow_redirects=False,
    )
    assert response.status_code in (401, 302, 303)