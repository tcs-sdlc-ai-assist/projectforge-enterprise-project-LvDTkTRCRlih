import asyncio
import uuid
from datetime import datetime
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base, get_db
from dependencies import create_session_cookie, serializer
from main import app
from models.department import Department
from models.project import Project, project_members
from models.user import User


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    future=True,
)


@event.listens_for(test_engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


test_async_session_factory = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with test_async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


def _hash_password(password: str) -> str:
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash(password)


def _make_session_cookie(user_id: str) -> str:
    return serializer.dumps({"user_id": user_id})


@pytest_asyncio.fixture
async def test_department(db_session: AsyncSession) -> Department:
    department = Department(
        id=str(uuid.uuid4()),
        name=f"Test Department {uuid.uuid4().hex[:6]}",
        description="A department for testing",
        head_id=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(department)
    await db_session.flush()
    await db_session.commit()
    return department


@pytest_asyncio.fixture
async def super_admin_user(
    db_session: AsyncSession,
    test_department: Department,
) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=f"superadmin_{uuid.uuid4().hex[:6]}",
        password_hash=_hash_password("testpassword123"),
        email=f"superadmin_{uuid.uuid4().hex[:6]}@test.com",
        first_name="Super",
        last_name="Admin",
        role="super_admin",
        department_id=test_department.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def project_manager_user(
    db_session: AsyncSession,
    test_department: Department,
) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=f"pm_{uuid.uuid4().hex[:6]}",
        password_hash=_hash_password("testpassword123"),
        email=f"pm_{uuid.uuid4().hex[:6]}@test.com",
        first_name="Project",
        last_name="Manager",
        role="project_manager",
        department_id=test_department.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def team_lead_user(
    db_session: AsyncSession,
    test_department: Department,
) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=f"tl_{uuid.uuid4().hex[:6]}",
        password_hash=_hash_password("testpassword123"),
        email=f"tl_{uuid.uuid4().hex[:6]}@test.com",
        first_name="Team",
        last_name="Lead",
        role="team_lead",
        department_id=test_department.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def developer_user(
    db_session: AsyncSession,
    test_department: Department,
) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=f"dev_{uuid.uuid4().hex[:6]}",
        password_hash=_hash_password("testpassword123"),
        email=f"dev_{uuid.uuid4().hex[:6]}@test.com",
        first_name="Dev",
        last_name="User",
        role="developer",
        department_id=test_department.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def inactive_user(
    db_session: AsyncSession,
    test_department: Department,
) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=f"inactive_{uuid.uuid4().hex[:6]}",
        password_hash=_hash_password("testpassword123"),
        email=f"inactive_{uuid.uuid4().hex[:6]}@test.com",
        first_name="Inactive",
        last_name="User",
        role="developer",
        department_id=test_department.id,
        is_active=False,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def authenticated_client_super_admin(
    client: httpx.AsyncClient,
    super_admin_user: User,
) -> httpx.AsyncClient:
    cookie_value = _make_session_cookie(super_admin_user.id)
    client.cookies.set("session", cookie_value)
    return client


@pytest_asyncio.fixture
async def authenticated_client_pm(
    client: httpx.AsyncClient,
    project_manager_user: User,
) -> httpx.AsyncClient:
    cookie_value = _make_session_cookie(project_manager_user.id)
    client.cookies.set("session", cookie_value)
    return client


@pytest_asyncio.fixture
async def authenticated_client_team_lead(
    client: httpx.AsyncClient,
    team_lead_user: User,
) -> httpx.AsyncClient:
    cookie_value = _make_session_cookie(team_lead_user.id)
    client.cookies.set("session", cookie_value)
    return client


@pytest_asyncio.fixture
async def authenticated_client_developer(
    client: httpx.AsyncClient,
    developer_user: User,
) -> httpx.AsyncClient:
    cookie_value = _make_session_cookie(developer_user.id)
    client.cookies.set("session", cookie_value)
    return client


@pytest_asyncio.fixture
async def test_project(
    db_session: AsyncSession,
    test_department: Department,
    super_admin_user: User,
) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name=f"Test Project {uuid.uuid4().hex[:6]}",
        key=f"TP{uuid.uuid4().hex[:4].upper()}",
        description="A project for testing purposes",
        department_id=test_department.id,
        owner_id=super_admin_user.id,
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(project)
    await db_session.flush()

    await db_session.execute(
        project_members.insert().values(
            project_id=project.id,
            user_id=super_admin_user.id,
        )
    )
    await db_session.flush()
    await db_session.commit()
    return project


@pytest_asyncio.fixture
async def test_project_with_members(
    db_session: AsyncSession,
    test_project: Project,
    project_manager_user: User,
    developer_user: User,
) -> Project:
    await db_session.execute(
        project_members.insert().values(
            project_id=test_project.id,
            user_id=project_manager_user.id,
        )
    )
    await db_session.execute(
        project_members.insert().values(
            project_id=test_project.id,
            user_id=developer_user.id,
        )
    )
    await db_session.flush()
    await db_session.commit()
    return test_project