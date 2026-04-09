import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base, get_db
from dependencies import create_session_cookie, SESSION_COOKIE_NAME
from main import app
from models.department import Department
from models.user import User

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_departments.db"

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


def _hash_password(password: str) -> str:
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash(password)


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def admin_user() -> User:
    async with test_session_factory() as session:
        user = User(
            id=str(uuid.uuid4()),
            username="testadmin",
            password_hash=_hash_password("adminpass123"),
            email="testadmin@projectforge.io",
            first_name="Test",
            last_name="Admin",
            role="super_admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def developer_user() -> User:
    async with test_session_factory() as session:
        user = User(
            id=str(uuid.uuid4()),
            username="testdev",
            password_hash=_hash_password("devpass123"),
            email="testdev@projectforge.io",
            first_name="Test",
            last_name="Developer",
            role="developer",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def project_manager_user() -> User:
    async with test_session_factory() as session:
        user = User(
            id=str(uuid.uuid4()),
            username="testpm",
            password_hash=_hash_password("pmpass123"),
            email="testpm@projectforge.io",
            first_name="Test",
            last_name="PM",
            role="project_manager",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def sample_department() -> Department:
    async with test_session_factory() as session:
        department = Department(
            id=str(uuid.uuid4()),
            name="Engineering",
            description="Software engineering team",
            head_id=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(department)
        await session.commit()
        await session.refresh(department)
        return department


def _make_session_cookie(user_id: str) -> dict:
    from itsdangerous import URLSafeTimedSerializer
    from config import settings

    serializer = URLSafeTimedSerializer(settings.SECRET_KEY)
    token = serializer.dumps({"user_id": user_id})
    return {SESSION_COOKIE_NAME: token}


@pytest.mark.asyncio
async def test_list_departments_as_admin(admin_user: User, sample_department: Department):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/departments", cookies=cookies, follow_redirects=False)
    assert response.status_code == 200
    assert "Engineering" in response.text


@pytest.mark.asyncio
async def test_list_departments_as_project_manager(
    project_manager_user: User, sample_department: Department
):
    cookies = _make_session_cookie(project_manager_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/departments", cookies=cookies, follow_redirects=False)
    assert response.status_code == 200
    assert "Engineering" in response.text


@pytest.mark.asyncio
async def test_list_departments_as_developer_redirects(developer_user: User):
    cookies = _make_session_cookie(developer_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/departments", cookies=cookies, follow_redirects=False)
    assert response.status_code == 303
    assert "/dashboard" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_list_departments_unauthenticated():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/departments", follow_redirects=False)
    assert response.status_code in (401, 303, 307)


@pytest.mark.asyncio
async def test_create_department_as_admin(admin_user: User):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/departments",
            data={
                "name": "Marketing",
                "description": "Marketing department",
                "head_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "/departments" in response.headers.get("location", "")

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.name == "Marketing")
        )
        department = result.scalar_one_or_none()
        assert department is not None
        assert department.name == "Marketing"
        assert department.description == "Marketing department"


@pytest.mark.asyncio
async def test_create_department_as_developer_forbidden(developer_user: User):
    cookies = _make_session_cookie(developer_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/departments",
            data={
                "name": "Forbidden Dept",
                "description": "Should not be created",
                "head_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code in (403, 303)

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.name == "Forbidden Dept")
        )
        department = result.scalar_one_or_none()
        assert department is None


@pytest.mark.asyncio
async def test_create_department_duplicate_name(
    admin_user: User, sample_department: Department
):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/departments",
            data={
                "name": "Engineering",
                "description": "Duplicate department",
                "head_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_create_department_empty_name(admin_user: User):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/departments",
            data={
                "name": "   ",
                "description": "Empty name department",
                "head_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_create_department_with_head(admin_user: User):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/departments",
            data={
                "name": "Design",
                "description": "Design team",
                "head_id": admin_user.id,
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.name == "Design")
        )
        department = result.scalar_one_or_none()
        assert department is not None
        assert department.head_id == admin_user.id


@pytest.mark.asyncio
async def test_update_department_as_admin(
    admin_user: User, sample_department: Department
):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{sample_department.id}/edit",
            data={
                "name": "Engineering Updated",
                "description": "Updated description",
                "head_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.id == sample_department.id)
        )
        department = result.scalar_one_or_none()
        assert department is not None
        assert department.name == "Engineering Updated"
        assert department.description == "Updated description"


@pytest.mark.asyncio
async def test_update_department_assign_head(
    admin_user: User, sample_department: Department
):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{sample_department.id}/edit",
            data={
                "name": sample_department.name,
                "description": sample_department.description or "",
                "head_id": admin_user.id,
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.id == sample_department.id)
        )
        department = result.scalar_one_or_none()
        assert department is not None
        assert department.head_id == admin_user.id


@pytest.mark.asyncio
async def test_update_department_as_developer_forbidden(
    developer_user: User, sample_department: Department
):
    cookies = _make_session_cookie(developer_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{sample_department.id}/edit",
            data={
                "name": "Should Not Update",
                "description": "Forbidden",
                "head_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code in (403, 303)

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.id == sample_department.id)
        )
        department = result.scalar_one_or_none()
        assert department is not None
        assert department.name == "Engineering"


@pytest.mark.asyncio
async def test_update_nonexistent_department(admin_user: User):
    cookies = _make_session_cookie(admin_user.id)
    fake_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{fake_id}/edit",
            data={
                "name": "Ghost Department",
                "description": "Does not exist",
                "head_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_delete_department_as_admin(
    admin_user: User, sample_department: Department
):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{sample_department.id}/delete",
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.id == sample_department.id)
        )
        department = result.scalar_one_or_none()
        assert department is None


@pytest.mark.asyncio
async def test_delete_department_as_developer_forbidden(
    developer_user: User, sample_department: Department
):
    cookies = _make_session_cookie(developer_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{sample_department.id}/delete",
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code in (403, 303)

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.id == sample_department.id)
        )
        department = result.scalar_one_or_none()
        assert department is not None


@pytest.mark.asyncio
async def test_cannot_delete_department_with_assigned_users(
    admin_user: User, sample_department: Department
):
    async with test_session_factory() as session:
        member_user = User(
            id=str(uuid.uuid4()),
            username="deptmember",
            password_hash=_hash_password("memberpass123"),
            email="deptmember@projectforge.io",
            first_name="Dept",
            last_name="Member",
            role="developer",
            department_id=sample_department.id,
            is_active=True,
        )
        session.add(member_user)
        await session.commit()

    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{sample_department.id}/delete",
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.id == sample_department.id)
        )
        department = result.scalar_one_or_none()
        assert department is not None


@pytest.mark.asyncio
async def test_delete_nonexistent_department(admin_user: User):
    cookies = _make_session_cookie(admin_user.id)
    fake_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{fake_id}/delete",
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_department_detail_page(
    admin_user: User, sample_department: Department
):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/departments/{sample_department.id}",
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 200
    assert "Engineering" in response.text


@pytest.mark.asyncio
async def test_department_detail_nonexistent(admin_user: User):
    cookies = _make_session_cookie(admin_user.id)
    fake_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/departments/{fake_id}",
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_edit_department_form_as_admin(
    admin_user: User, sample_department: Department
):
    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/departments/{sample_department.id}/edit",
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_edit_department_form_nonexistent(admin_user: User):
    cookies = _make_session_cookie(admin_user.id)
    fake_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/departments/{fake_id}/edit",
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_search_departments(admin_user: User, sample_department: Department):
    async with test_session_factory() as session:
        dept2 = Department(
            id=str(uuid.uuid4()),
            name="Marketing",
            description="Marketing team",
            head_id=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(dept2)
        await session.commit()

    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/departments?search=Marketing",
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 200
    assert "Marketing" in response.text


@pytest.mark.asyncio
async def test_update_department_duplicate_name(
    admin_user: User, sample_department: Department
):
    async with test_session_factory() as session:
        dept2 = Department(
            id=str(uuid.uuid4()),
            name="Sales",
            description="Sales team",
            head_id=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(dept2)
        await session.commit()
        dept2_id = dept2.id

    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{dept2_id}/edit",
            data={
                "name": "Engineering",
                "description": "Trying to duplicate",
                "head_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.id == dept2_id)
        )
        department = result.scalar_one_or_none()
        assert department is not None
        assert department.name == "Sales"


@pytest.mark.asyncio
async def test_update_department_remove_head(
    admin_user: User, sample_department: Department
):
    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.id == sample_department.id)
        )
        dept = result.scalar_one()
        dept.head_id = admin_user.id
        await session.commit()

    cookies = _make_session_cookie(admin_user.id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/departments/{sample_department.id}/edit",
            data={
                "name": sample_department.name,
                "description": sample_department.description or "",
                "head_id": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
    assert response.status_code == 303

    async with test_session_factory() as session:
        result = await session.execute(
            select(Department).where(Department.id == sample_department.id)
        )
        department = result.scalar_one_or_none()
        assert department is not None
        assert department.head_id is None