import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import (
    clear_flash,
    clear_session_cookie,
    create_session_cookie,
    get_current_user_optional,
    get_flash,
    set_flash,
)
from models.audit_log import AuditLog
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_templates():
    from pathlib import Path

    from fastapi.templating import Jinja2Templates

    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    return Jinja2Templates(directory=str(templates_dir))


@router.get("/login")
async def login_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user_optional(request, db)
    if user is not None:
        return RedirectResponse(url="/dashboard", status_code=302)

    templates = _get_templates()
    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "auth/login.html",
        context={
            "current_user": None,
            "flash_messages": flash_messages,
            "error": None,
            "username": "",
        },
    )
    clear_flash(response)
    return response


@router.post("/login")
async def login_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    username: str = Form(""),
    password: str = Form(""),
):
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    templates = _get_templates()

    username = username.strip()
    password = password.strip()

    if not username or not password:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            context={
                "current_user": None,
                "flash_messages": [],
                "error": "Username and password are required.",
                "username": username,
            },
            status_code=400,
        )

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not pwd_context.verify(password, user.password_hash):
        logger.warning("Failed login attempt for username: %s", username)
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            context={
                "current_user": None,
                "flash_messages": [],
                "error": "Invalid username or password.",
                "username": username,
            },
            status_code=401,
        )

    if not user.is_active:
        logger.warning("Login attempt for inactive user: %s", username)
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            context={
                "current_user": None,
                "flash_messages": [],
                "error": "Your account has been deactivated. Please contact an administrator.",
                "username": username,
            },
            status_code=403,
        )

    audit_entry = AuditLog(
        id=str(uuid.uuid4()),
        actor_id=user.id,
        action="login",
        entity_type="user",
        entity_id=user.id,
        changes=None,
        timestamp=datetime.utcnow(),
    )
    db.add(audit_entry)
    await db.flush()

    response = RedirectResponse(url="/dashboard", status_code=302)
    create_session_cookie(response, user.id)
    set_flash(response, "Login successful. Welcome back!", "success")

    logger.info("User '%s' logged in successfully.", username)
    return response


@router.get("/register")
async def register_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user_optional(request, db)
    if user is not None:
        return RedirectResponse(url="/dashboard", status_code=302)

    templates = _get_templates()
    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "auth/register.html",
        context={
            "current_user": None,
            "flash_messages": flash_messages,
            "errors": [],
            "form_data": None,
        },
    )
    clear_flash(response)
    return response


@router.post("/register")
async def register_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    username: str = Form(""),
    email: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
):
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    templates = _get_templates()

    username = username.strip()
    email = email.strip()
    first_name = first_name.strip()
    last_name = last_name.strip()

    form_data = {
        "username": username,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
    }

    errors: list[str] = []

    if not username:
        errors.append("Username is required.")
    elif len(username) < 3:
        errors.append("Username must be at least 3 characters long.")
    elif len(username) > 150:
        errors.append("Username must be at most 150 characters long.")

    if not email:
        errors.append("Email is required.")
    elif "@" not in email or "." not in email:
        errors.append("Please enter a valid email address.")

    if not password:
        errors.append("Password is required.")
    elif len(password) < 8:
        errors.append("Password must be at least 8 characters long.")

    if not password_confirm:
        errors.append("Password confirmation is required.")
    elif password != password_confirm:
        errors.append("Passwords do not match.")

    if not errors and username:
        result = await db.execute(select(User).where(User.username == username))
        existing_user = result.scalar_one_or_none()
        if existing_user is not None:
            errors.append("Username is already taken. Please choose a different one.")

    if not errors and email:
        result = await db.execute(select(User).where(User.email == email))
        existing_email = result.scalar_one_or_none()
        if existing_email is not None:
            errors.append("An account with this email already exists.")

    if errors:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            context={
                "current_user": None,
                "flash_messages": [],
                "errors": errors,
                "form_data": form_data,
            },
            status_code=400,
        )

    hashed_password = pwd_context.hash(password)

    new_user = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=hashed_password,
        email=email if email else None,
        first_name=first_name if first_name else None,
        last_name=last_name if last_name else None,
        role="developer",
        department_id=None,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    audit_entry = AuditLog(
        id=str(uuid.uuid4()),
        actor_id=new_user.id,
        action="create",
        entity_type="user",
        entity_id=new_user.id,
        changes=f"User '{username}' registered",
        timestamp=datetime.utcnow(),
    )
    db.add(audit_entry)
    await db.flush()

    response = RedirectResponse(url="/dashboard", status_code=302)
    create_session_cookie(response, new_user.id)
    set_flash(response, "Account created successfully. Welcome to ProjectForge!", "success")

    logger.info("New user '%s' registered successfully (id=%s).", username, new_user.id)
    return response


@router.post("/logout")
async def logout_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user_optional(request, db)

    if user is not None:
        audit_entry = AuditLog(
            id=str(uuid.uuid4()),
            actor_id=user.id,
            action="logout",
            entity_type="user",
            entity_id=user.id,
            changes=None,
            timestamp=datetime.utcnow(),
        )
        db.add(audit_entry)
        await db.flush()
        logger.info("User '%s' logged out.", user.username)

    response = RedirectResponse(url="/auth/login", status_code=302)
    clear_session_cookie(response)
    set_flash(response, "You have been logged out.", "info")
    return response


@router.get("/logout")
async def logout_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user_optional(request, db)

    if user is not None:
        audit_entry = AuditLog(
            id=str(uuid.uuid4()),
            actor_id=user.id,
            action="logout",
            entity_type="user",
            entity_id=user.id,
            changes=None,
            timestamp=datetime.utcnow(),
        )
        db.add(audit_entry)
        await db.flush()
        logger.info("User '%s' logged out via GET.", user.username)

    response = RedirectResponse(url="/auth/login", status_code=302)
    clear_session_cookie(response)
    set_flash(response, "You have been logged out.", "info")
    return response