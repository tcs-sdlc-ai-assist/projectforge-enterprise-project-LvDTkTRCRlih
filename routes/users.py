import json
import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from passlib.context import CryptContext
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import (
    clear_flash,
    get_current_user,
    get_flash,
    require_role,
    set_flash,
)
from models.audit_log import AuditLog
from models.department import Department
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

VALID_ROLES = ["super_admin", "project_manager", "team_lead", "developer"]

PER_PAGE = 20


async def _log_audit(
    db: AsyncSession,
    actor_id: str,
    action: str,
    entity_id: str,
    changes: str | None = None,
) -> None:
    audit_entry = AuditLog(
        id=str(uuid.uuid4()),
        actor_id=actor_id,
        action=action,
        entity_type="user",
        entity_id=entity_id,
        changes=changes,
        timestamp=datetime.utcnow(),
    )
    db.add(audit_entry)


@router.get("")
async def list_users(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
    search: str = "",
    role: str = "",
    page: int = 1,
):
    flash_messages = get_flash(request)

    query = select(User)

    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                User.username.ilike(search_term),
                User.email.ilike(search_term),
                User.first_name.ilike(search_term),
                User.last_name.ilike(search_term),
            )
        )

    if role:
        query = query.where(User.role == role)

    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    total_pages = max(1, (total_count + PER_PAGE - 1) // PER_PAGE)

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * PER_PAGE
    query = query.order_by(User.username).offset(offset).limit(PER_PAGE)

    result = await db.execute(query)
    users = result.scalars().all()

    response = templates.TemplateResponse(
        request,
        "users/list.html",
        context={
            "current_user": current_user,
            "users": users,
            "search": search,
            "role_filter": role,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.get("/create")
async def create_user_form(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
):
    flash_messages = get_flash(request)

    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    response = templates.TemplateResponse(
        request,
        "users/form.html",
        context={
            "current_user": current_user,
            "user": None,
            "departments": departments,
            "errors": [],
            "form_data": None,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.post("/create")
async def create_user_handler(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
    username: str = Form(""),
    email: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    role: str = Form(""),
    department_id: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
):
    errors: list[str] = []
    form_data = {
        "username": username.strip(),
        "email": email.strip(),
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "role": role,
        "department_id": department_id,
    }

    username_clean = username.strip()
    email_clean = email.strip()

    if not username_clean or len(username_clean) < 3:
        errors.append("Username must be at least 3 characters long.")
    if len(username_clean) > 150:
        errors.append("Username must be at most 150 characters long.")

    if not email_clean:
        errors.append("Email is required.")

    if not role or role not in VALID_ROLES:
        errors.append(f"Role must be one of: {', '.join(VALID_ROLES)}.")

    if not password or len(password) < 8:
        errors.append("Password must be at least 8 characters long.")

    if password != password_confirm:
        errors.append("Passwords do not match.")

    if not errors:
        existing_username = await db.execute(
            select(User).where(User.username == username_clean)
        )
        if existing_username.scalar_one_or_none() is not None:
            errors.append(f"Username '{username_clean}' is already taken.")

        if email_clean:
            existing_email = await db.execute(
                select(User).where(User.email == email_clean)
            )
            if existing_email.scalar_one_or_none() is not None:
                errors.append(f"Email '{email_clean}' is already in use.")

    if errors:
        dept_result = await db.execute(select(Department).order_by(Department.name))
        departments = dept_result.scalars().all()

        return templates.TemplateResponse(
            request,
            "users/form.html",
            context={
                "current_user": current_user,
                "user": None,
                "departments": departments,
                "errors": errors,
                "form_data": form_data,
                "flash_messages": [],
            },
        )

    password_hash = pwd_context.hash(password)
    new_user_id = str(uuid.uuid4())

    new_user = User(
        id=new_user_id,
        username=username_clean,
        password_hash=password_hash,
        email=email_clean if email_clean else None,
        first_name=first_name.strip() if first_name.strip() else None,
        last_name=last_name.strip() if last_name.strip() else None,
        role=role,
        department_id=department_id if department_id else None,
        is_active=True,
    )
    db.add(new_user)

    await _log_audit(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_id=new_user_id,
        changes=json.dumps({
            "username": username_clean,
            "email": email_clean,
            "role": role,
            "department_id": department_id if department_id else None,
        }),
    )

    await db.flush()

    logger.info(
        "User '%s' created by '%s'.",
        username_clean,
        current_user.username,
    )

    response = RedirectResponse(url="/users", status_code=303)
    set_flash(response, f"User '{username_clean}' created successfully.", "success")
    return response


@router.get("/{user_id}/edit")
async def edit_user_form(
    request: Request,
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
):
    flash_messages = get_flash(request)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    response = templates.TemplateResponse(
        request,
        "users/form.html",
        context={
            "current_user": current_user,
            "user": user,
            "departments": departments,
            "errors": [],
            "form_data": None,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.post("/{user_id}/edit")
async def edit_user_handler(
    request: Request,
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
    username: str = Form(""),
    email: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    role: str = Form(""),
    department_id: str = Form(""),
    is_active: str = Form(""),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    errors: list[str] = []
    form_data = {
        "username": username.strip(),
        "email": email.strip(),
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "role": role,
        "department_id": department_id,
        "is_active": is_active == "true",
    }

    username_clean = username.strip()
    email_clean = email.strip()

    if not username_clean or len(username_clean) < 3:
        errors.append("Username must be at least 3 characters long.")
    if len(username_clean) > 150:
        errors.append("Username must be at most 150 characters long.")

    if not email_clean:
        errors.append("Email is required.")

    if not role or role not in VALID_ROLES:
        errors.append(f"Role must be one of: {', '.join(VALID_ROLES)}.")

    if not errors:
        if username_clean != user.username:
            existing_username = await db.execute(
                select(User).where(
                    User.username == username_clean,
                    User.id != user_id,
                )
            )
            if existing_username.scalar_one_or_none() is not None:
                errors.append(f"Username '{username_clean}' is already taken.")

        if email_clean and email_clean != user.email:
            existing_email = await db.execute(
                select(User).where(
                    User.email == email_clean,
                    User.id != user_id,
                )
            )
            if existing_email.scalar_one_or_none() is not None:
                errors.append(f"Email '{email_clean}' is already in use.")

    if errors:
        dept_result = await db.execute(select(Department).order_by(Department.name))
        departments = dept_result.scalars().all()

        return templates.TemplateResponse(
            request,
            "users/form.html",
            context={
                "current_user": current_user,
                "user": user,
                "departments": departments,
                "errors": errors,
                "form_data": form_data,
                "flash_messages": [],
            },
        )

    changes: dict = {}

    if username_clean != user.username:
        changes["username"] = {"old": user.username, "new": username_clean}
        user.username = username_clean

    if email_clean != user.email:
        changes["email"] = {"old": user.email, "new": email_clean}
        user.email = email_clean if email_clean else None

    new_first_name = first_name.strip() if first_name.strip() else None
    if new_first_name != user.first_name:
        changes["first_name"] = {"old": user.first_name, "new": new_first_name}
        user.first_name = new_first_name

    new_last_name = last_name.strip() if last_name.strip() else None
    if new_last_name != user.last_name:
        changes["last_name"] = {"old": user.last_name, "new": new_last_name}
        user.last_name = new_last_name

    if role != user.role:
        changes["role"] = {"old": user.role, "new": role}
        user.role = role

    new_department_id = department_id if department_id else None
    if new_department_id != user.department_id:
        changes["department_id"] = {"old": user.department_id, "new": new_department_id}
        user.department_id = new_department_id

    new_is_active = is_active == "true"
    if new_is_active != user.is_active:
        changes["is_active"] = {"old": user.is_active, "new": new_is_active}
        user.is_active = new_is_active

    user.updated_at = datetime.utcnow()

    if changes:
        await _log_audit(
            db=db,
            actor_id=current_user.id,
            action="update",
            entity_id=user_id,
            changes=json.dumps(changes),
        )

    await db.flush()

    logger.info(
        "User '%s' (id=%s) updated by '%s'.",
        user.username,
        user_id,
        current_user.username,
    )

    response = RedirectResponse(url="/users", status_code=303)
    set_flash(response, f"User '{user.username}' updated successfully.", "success")
    return response


@router.post("/{user_id}/toggle-active")
async def toggle_user_active(
    request: Request,
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        response = RedirectResponse(url="/users", status_code=303)
        set_flash(response, "You cannot deactivate your own account.", "error")
        return response

    old_active = user.is_active
    user.is_active = not user.is_active
    user.updated_at = datetime.utcnow()

    await _log_audit(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_id=user_id,
        changes=json.dumps({
            "is_active": {"old": old_active, "new": user.is_active},
        }),
    )

    await db.flush()

    status_text = "activated" if user.is_active else "deactivated"
    logger.info(
        "User '%s' (id=%s) %s by '%s'.",
        user.username,
        user_id,
        status_text,
        current_user.username,
    )

    response = RedirectResponse(url="/users", status_code=303)
    set_flash(
        response,
        f"User '{user.username}' has been {status_text}.",
        "success",
    )
    return response