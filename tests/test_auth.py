import uuid
from unittest.mock import patch

import pytest
import httpx
from httpx import ASGITransport

from main import app
from database import Base, engine, async_session_factory
from models.user import User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def test_user():
    async with async_session_factory() as session:
        user = User(
            id=str(uuid.uuid4()),
            username="testuser",
            password_hash=pwd_context.hash("testpassword123"),
            email="testuser@example.com",
            first_name="Test",
            last_name="User",
            role="developer",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
async def inactive_user():
    async with async_session_factory() as session:
        user = User(
            id=str(uuid.uuid4()),
            username="inactiveuser",
            password_hash=pwd_context.hash("testpassword123"),
            email="inactive@example.com",
            first_name="Inactive",
            last_name="User",
            role="developer",
            is_active=False,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


# ---------------------------------------------------------------------------
# Login Page (GET)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_page_renders(client: httpx.AsyncClient):
    response = await client.get("/auth/login")
    assert response.status_code == 200
    assert "Sign in to your account" in response.text


@pytest.mark.asyncio
async def test_login_page_redirects_authenticated_user(
    client: httpx.AsyncClient, test_user: User
):
    login_response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "testpassword123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302
    cookies = login_response.cookies

    response = await client.get("/auth/login", cookies=cookies, follow_redirects=False)
    assert response.status_code == 302
    assert "/dashboard" in response.headers.get("location", "")


# ---------------------------------------------------------------------------
# Login Submit (POST)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_valid_credentials(client: httpx.AsyncClient, test_user: User):
    response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "testpassword123"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/dashboard" in response.headers.get("location", "")
    assert "session" in response.cookies


@pytest.mark.asyncio
async def test_login_invalid_password(client: httpx.AsyncClient, test_user: User):
    response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "wrongpassword"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert "Invalid username or password" in response.text


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/login",
        data={"username": "nosuchuser", "password": "somepassword"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert "Invalid username or password" in response.text


@pytest.mark.asyncio
async def test_login_empty_fields(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/login",
        data={"username": "", "password": ""},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Username and password are required" in response.text


@pytest.mark.asyncio
async def test_login_missing_username(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/login",
        data={"username": "", "password": "somepassword"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Username and password are required" in response.text


@pytest.mark.asyncio
async def test_login_missing_password(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": ""},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Username and password are required" in response.text


@pytest.mark.asyncio
async def test_login_inactive_user(
    client: httpx.AsyncClient, inactive_user: User
):
    response = await client.post(
        "/auth/login",
        data={"username": "inactiveuser", "password": "testpassword123"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "deactivated" in response.text


# ---------------------------------------------------------------------------
# Registration Page (GET)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_page_renders(client: httpx.AsyncClient):
    response = await client.get("/auth/register")
    assert response.status_code == 200
    assert "Create your account" in response.text


@pytest.mark.asyncio
async def test_register_page_redirects_authenticated_user(
    client: httpx.AsyncClient, test_user: User
):
    login_response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "testpassword123"},
        follow_redirects=False,
    )
    cookies = login_response.cookies

    response = await client.get(
        "/auth/register", cookies=cookies, follow_redirects=False
    )
    assert response.status_code == 302
    assert "/dashboard" in response.headers.get("location", "")


# ---------------------------------------------------------------------------
# Registration Submit (POST)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_valid_data(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/register",
        data={
            "username": "newuser",
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "password": "securepassword123",
            "password_confirm": "securepassword123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/dashboard" in response.headers.get("location", "")
    assert "session" in response.cookies


@pytest.mark.asyncio
async def test_register_duplicate_username(
    client: httpx.AsyncClient, test_user: User
):
    response = await client.post(
        "/auth/register",
        data={
            "username": "testuser",
            "email": "another@example.com",
            "first_name": "Another",
            "last_name": "User",
            "password": "securepassword123",
            "password_confirm": "securepassword123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "already taken" in response.text


@pytest.mark.asyncio
async def test_register_duplicate_email(
    client: httpx.AsyncClient, test_user: User
):
    response = await client.post(
        "/auth/register",
        data={
            "username": "differentuser",
            "email": "testuser@example.com",
            "first_name": "Different",
            "last_name": "User",
            "password": "securepassword123",
            "password_confirm": "securepassword123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "already exists" in response.text


@pytest.mark.asyncio
async def test_register_missing_username(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/register",
        data={
            "username": "",
            "email": "nouser@example.com",
            "first_name": "",
            "last_name": "",
            "password": "securepassword123",
            "password_confirm": "securepassword123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Username is required" in response.text


@pytest.mark.asyncio
async def test_register_short_username(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/register",
        data={
            "username": "ab",
            "email": "short@example.com",
            "first_name": "",
            "last_name": "",
            "password": "securepassword123",
            "password_confirm": "securepassword123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "at least 3 characters" in response.text


@pytest.mark.asyncio
async def test_register_missing_email(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/register",
        data={
            "username": "noemailuser",
            "email": "",
            "first_name": "",
            "last_name": "",
            "password": "securepassword123",
            "password_confirm": "securepassword123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Email is required" in response.text


@pytest.mark.asyncio
async def test_register_invalid_email(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/register",
        data={
            "username": "bademailuser",
            "email": "notanemail",
            "first_name": "",
            "last_name": "",
            "password": "securepassword123",
            "password_confirm": "securepassword123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "valid email" in response.text


@pytest.mark.asyncio
async def test_register_short_password(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/register",
        data={
            "username": "shortpwuser",
            "email": "shortpw@example.com",
            "first_name": "",
            "last_name": "",
            "password": "short",
            "password_confirm": "short",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "at least 8 characters" in response.text


@pytest.mark.asyncio
async def test_register_password_mismatch(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/register",
        data={
            "username": "mismatchuser",
            "email": "mismatch@example.com",
            "first_name": "",
            "last_name": "",
            "password": "securepassword123",
            "password_confirm": "differentpassword",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "do not match" in response.text


@pytest.mark.asyncio
async def test_register_missing_password(client: httpx.AsyncClient):
    response = await client.post(
        "/auth/register",
        data={
            "username": "nopwuser",
            "email": "nopw@example.com",
            "first_name": "",
            "last_name": "",
            "password": "",
            "password_confirm": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Password is required" in response.text


# ---------------------------------------------------------------------------
# Logout (POST)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_clears_session(client: httpx.AsyncClient, test_user: User):
    login_response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "testpassword123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302
    cookies = login_response.cookies

    logout_response = await client.post(
        "/auth/logout",
        cookies=cookies,
        follow_redirects=False,
    )
    assert logout_response.status_code == 302
    assert "/auth/login" in logout_response.headers.get("location", "")

    session_cookie = logout_response.cookies.get("session")
    if session_cookie is not None:
        assert session_cookie == "" or session_cookie == '""'


@pytest.mark.asyncio
async def test_logout_get_also_works(client: httpx.AsyncClient, test_user: User):
    login_response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "testpassword123"},
        follow_redirects=False,
    )
    cookies = login_response.cookies

    logout_response = await client.get(
        "/auth/logout",
        cookies=cookies,
        follow_redirects=False,
    )
    assert logout_response.status_code == 302
    assert "/auth/login" in logout_response.headers.get("location", "")


@pytest.mark.asyncio
async def test_logout_without_session(client: httpx.AsyncClient):
    response = await client.post("/auth/logout", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in response.headers.get("location", "")


# ---------------------------------------------------------------------------
# Protected Route Access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_redirects_unauthenticated(client: httpx.AsyncClient):
    response = await client.get("/dashboard", follow_redirects=False)
    assert response.status_code in (401, 302, 303)


@pytest.mark.asyncio
async def test_dashboard_accessible_when_authenticated(
    client: httpx.AsyncClient, test_user: User
):
    login_response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "testpassword123"},
        follow_redirects=False,
    )
    cookies = login_response.cookies

    response = await client.get(
        "/dashboard", cookies=cookies, follow_redirects=False
    )
    assert response.status_code == 200
    assert "Dashboard" in response.text


@pytest.mark.asyncio
async def test_projects_requires_authentication(client: httpx.AsyncClient):
    response = await client.get("/projects", follow_redirects=False)
    assert response.status_code in (401, 302, 303)


# ---------------------------------------------------------------------------
# Session Cookie Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_session_cookie_rejected(client: httpx.AsyncClient):
    response = await client.get(
        "/dashboard",
        cookies={"session": "invalid-garbage-token"},
        follow_redirects=False,
    )
    assert response.status_code in (401, 302, 303)


@pytest.mark.asyncio
async def test_login_sets_httponly_cookie(
    client: httpx.AsyncClient, test_user: User
):
    response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "testpassword123"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "session=" in set_cookie_header
    assert "httponly" in set_cookie_header.lower()