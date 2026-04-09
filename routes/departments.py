import json
import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import (
    clear_flash,
    get_current_user,
    get_current_user_optional,
    get_flash,
    require_role,
    set_flash,
)
from models.audit_log import AuditLog
from models.department import Department
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/departments")
async def list_departments(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    search: str = "",
):
    if current_user.role not in ["super_admin", "admin", "project_manager"]:
        set_flash(response, "You do not have permission to view departments.", "error")
        resp = RedirectResponse(url="/dashboard", status_code=303)
        set_flash(resp, "You do not have permission to view departments.", "error")
        return resp

    stmt = select(Department)
    if search:
        stmt = stmt.where(Department.name.ilike(f"%{search}%"))
    stmt = stmt.order_by(Department.name)

    result = await db.execute(stmt)
    departments = result.scalars().all()

    users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.username)
    )
    users = users_result.scalars().all()

    flash_messages = get_flash(request)
    clear_flash(response)

    return templates.TemplateResponse(
        request,
        "departments/list.html",
        context={
            "departments": departments,
            "users": users,
            "current_user": current_user,
            "search": search,
            "flash_messages": flash_messages,
        },
    )


@router.post("/departments")
async def create_department(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
    name: str = Form(...),
    description: str = Form(""),
    head_id: str = Form(""),
):
    name = name.strip()
    if not name:
        resp = RedirectResponse(url="/departments", status_code=303)
        set_flash(resp, "Department name is required.", "error")
        return resp

    existing_result = await db.execute(
        select(Department).where(func.lower(Department.name) == name.lower())
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        resp = RedirectResponse(url="/departments", status_code=303)
        set_flash(resp, f"A department with the name '{name}' already exists.", "error")
        return resp

    department = Department(
        id=str(uuid.uuid4()),
        name=name,
        description=description.strip() if description else None,
        head_id=head_id if head_id else None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(department)
    await db.flush()

    audit_entry = AuditLog(
        id=str(uuid.uuid4()),
        actor_id=current_user.id,
        action="create",
        entity_type="department",
        entity_id=department.id,
        changes=json.dumps({"name": name, "description": description, "head_id": head_id or None}),
        timestamp=datetime.utcnow(),
    )
    db.add(audit_entry)

    logger.info(
        "Department '%s' created by user '%s' (id=%s).",
        name,
        current_user.username,
        current_user.id,
    )

    resp = RedirectResponse(url="/departments", status_code=303)
    set_flash(resp, f"Department '{name}' created successfully.", "success")
    return resp


@router.get("/departments/{department_id}")
async def department_detail(
    request: Request,
    response: Response,
    department_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(
        select(Department).where(Department.id == department_id)
    )
    department = result.scalar_one_or_none()

    if department is None:
        resp = RedirectResponse(url="/departments", status_code=303)
        set_flash(resp, "Department not found.", "error")
        return resp

    flash_messages = get_flash(request)
    clear_flash(response)

    return templates.TemplateResponse(
        request,
        "departments/list.html",
        context={
            "departments": [department],
            "users": [],
            "current_user": current_user,
            "search": "",
            "flash_messages": flash_messages,
        },
    )


@router.get("/departments/{department_id}/edit")
async def edit_department_form(
    request: Request,
    response: Response,
    department_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
):
    result = await db.execute(
        select(Department).where(Department.id == department_id)
    )
    department = result.scalar_one_or_none()

    if department is None:
        resp = RedirectResponse(url="/departments", status_code=303)
        set_flash(resp, "Department not found.", "error")
        return resp

    users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.username)
    )
    users = users_result.scalars().all()

    flash_messages = get_flash(request)
    clear_flash(response)

    return templates.TemplateResponse(
        request,
        "departments/list.html",
        context={
            "departments": [department],
            "users": users,
            "current_user": current_user,
            "search": "",
            "flash_messages": flash_messages,
            "editing_department": department,
        },
    )


@router.post("/departments/{department_id}/edit")
async def update_department(
    request: Request,
    department_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
    name: str = Form(...),
    description: str = Form(""),
    head_id: str = Form(""),
):
    result = await db.execute(
        select(Department).where(Department.id == department_id)
    )
    department = result.scalar_one_or_none()

    if department is None:
        resp = RedirectResponse(url="/departments", status_code=303)
        set_flash(resp, "Department not found.", "error")
        return resp

    name = name.strip()
    if not name:
        resp = RedirectResponse(url=f"/departments/{department_id}/edit", status_code=303)
        set_flash(resp, "Department name is required.", "error")
        return resp

    existing_result = await db.execute(
        select(Department).where(
            func.lower(Department.name) == name.lower(),
            Department.id != department_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        resp = RedirectResponse(url=f"/departments/{department_id}/edit", status_code=303)
        set_flash(resp, f"A department with the name '{name}' already exists.", "error")
        return resp

    changes = {}
    if department.name != name:
        changes["name"] = {"old": department.name, "new": name}
        department.name = name

    new_description = description.strip() if description else None
    if department.description != new_description:
        changes["description"] = {"old": department.description, "new": new_description}
        department.description = new_description

    new_head_id = head_id if head_id else None
    if department.head_id != new_head_id:
        changes["head_id"] = {"old": department.head_id, "new": new_head_id}
        department.head_id = new_head_id

    department.updated_at = datetime.utcnow()
    await db.flush()

    if changes:
        audit_entry = AuditLog(
            id=str(uuid.uuid4()),
            actor_id=current_user.id,
            action="update",
            entity_type="department",
            entity_id=department.id,
            changes=json.dumps(changes),
            timestamp=datetime.utcnow(),
        )
        db.add(audit_entry)

    logger.info(
        "Department '%s' (id=%s) updated by user '%s' (id=%s).",
        department.name,
        department.id,
        current_user.username,
        current_user.id,
    )

    resp = RedirectResponse(url="/departments", status_code=303)
    set_flash(resp, f"Department '{department.name}' updated successfully.", "success")
    return resp


@router.post("/departments/{department_id}/delete")
async def delete_department(
    request: Request,
    department_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["super_admin", "admin"]))],
):
    result = await db.execute(
        select(Department).where(Department.id == department_id)
    )
    department = result.scalar_one_or_none()

    if department is None:
        resp = RedirectResponse(url="/departments", status_code=303)
        set_flash(resp, "Department not found.", "error")
        return resp

    member_count_result = await db.execute(
        select(func.count()).select_from(User).where(User.department_id == department_id)
    )
    member_count = member_count_result.scalar() or 0

    if member_count > 0:
        resp = RedirectResponse(url="/departments", status_code=303)
        set_flash(
            resp,
            f"Cannot delete department '{department.name}' because it has {member_count} assigned user(s). "
            f"Reassign or remove users first.",
            "error",
        )
        return resp

    department_name = department.name

    audit_entry = AuditLog(
        id=str(uuid.uuid4()),
        actor_id=current_user.id,
        action="delete",
        entity_type="department",
        entity_id=department_id,
        changes=json.dumps({"name": department_name}),
        timestamp=datetime.utcnow(),
    )
    db.add(audit_entry)

    await db.delete(department)
    await db.flush()

    logger.info(
        "Department '%s' (id=%s) deleted by user '%s' (id=%s).",
        department_name,
        department_id,
        current_user.username,
        current_user.id,
    )

    resp = RedirectResponse(url="/departments", status_code=303)
    set_flash(resp, f"Department '{department_name}' deleted successfully.", "success")
    return resp