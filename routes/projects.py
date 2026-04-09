import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from models.label import Label
from models.project import Project, project_members
from models.sprint import Sprint
from models.ticket import Ticket
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


async def _log_audit(
    db: AsyncSession,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    changes: str | None = None,
) -> None:
    audit = AuditLog(
        id=str(uuid.uuid4()),
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
        timestamp=datetime.utcnow(),
    )
    db.add(audit)


@router.get("/projects")
async def list_projects(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    search: str = "",
    status: str = "",
    sort: str = "name",
    page: int = 1,
):
    per_page = 20
    query = select(Project).options(
        selectinload(Project.department),
        selectinload(Project.owner),
        selectinload(Project.members),
    )

    if search:
        search_term = f"%{search}%"
        query = query.where(
            (Project.name.ilike(search_term)) | (Project.key.ilike(search_term))
        )

    if status:
        query = query.where(Project.status == status)

    if sort == "created_at":
        query = query.order_by(Project.created_at.desc())
    elif sort == "updated_at":
        query = query.order_by(Project.updated_at.desc())
    elif sort == "status":
        query = query.order_by(Project.status)
    else:
        query = query.order_by(Project.name)

    count_query = select(func.count()).select_from(Project)
    if search:
        search_term = f"%{search}%"
        count_query = count_query.where(
            (Project.name.ilike(search_term)) | (Project.key.ilike(search_term))
        )
    if status:
        count_query = count_query.where(Project.status == status)

    total_result = await db.execute(count_query)
    total_count = total_result.scalar() or 0
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    projects = result.scalars().unique().all()

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "projects/list.html",
        context={
            "current_user": current_user,
            "projects": projects,
            "search": search,
            "status": status,
            "sort": sort,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": total_pages,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.get("/projects/create")
async def create_project_form(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(["super_admin", "admin", "project_manager"])),
    ],
):
    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "projects/form.html",
        context={
            "current_user": current_user,
            "project": None,
            "departments": departments,
            "errors": [],
            "form_data": None,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.post("/projects/create")
async def create_project(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(["super_admin", "admin", "project_manager"])),
    ],
    name: str = Form(""),
    key: str = Form(""),
    description: str = Form(""),
    department_id: str = Form(""),
):
    errors = []
    name = name.strip()
    key = key.strip().upper()
    description = description.strip()

    if not name:
        errors.append("Project name is required.")
    if not key:
        errors.append("Project key is required.")
    elif len(key) > 10:
        errors.append("Project key must be 10 characters or fewer.")

    if key:
        existing = await db.execute(select(Project).where(Project.key == key))
        if existing.scalar_one_or_none():
            errors.append(f"Project key '{key}' is already in use.")

    form_data = {
        "name": name,
        "key": key,
        "description": description,
        "department_id": department_id,
    }

    if errors:
        dept_result = await db.execute(select(Department).order_by(Department.name))
        departments = dept_result.scalars().all()
        return templates.TemplateResponse(
            request,
            "projects/form.html",
            context={
                "current_user": current_user,
                "project": None,
                "departments": departments,
                "errors": errors,
                "form_data": form_data,
                "flash_messages": [],
            },
        )

    project = Project(
        id=str(uuid.uuid4()),
        name=name,
        key=key,
        description=description if description else None,
        department_id=department_id if department_id else None,
        owner_id=current_user.id,
        status="planning",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(project)
    await db.flush()

    stmt = project_members.insert().values(
        project_id=project.id,
        user_id=current_user.id,
    )
    await db.execute(stmt)

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="create",
        entity_type="project",
        entity_id=project.id,
        changes=json.dumps({"name": name, "key": key, "status": "planning"}),
    )

    await db.flush()

    response = RedirectResponse(
        url=f"/projects/{project.id}", status_code=303
    )
    set_flash(response, f"Project '{name}' created successfully.", "success")
    return response


@router.get("/projects/{project_id}")
async def project_detail(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.department),
            selectinload(Project.owner),
            selectinload(Project.members),
            selectinload(Project.sprints),
            selectinload(Project.tickets).selectinload(Ticket.assignee),
            selectinload(Project.labels),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    members = project.members or []
    sprints = project.sprints or []
    tickets = project.tickets or []

    recent_tickets = sorted(
        tickets, key=lambda t: t.created_at or datetime.min, reverse=True
    )[:10]

    member_ids = {m.id for m in members}
    available_users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.username)
    )
    all_users = available_users_result.scalars().all()
    available_users = [u for u in all_users if u.id not in member_ids]

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "projects/detail.html",
        context={
            "current_user": current_user,
            "project": project,
            "members": members,
            "sprints": sprints,
            "tickets": tickets,
            "recent_tickets": recent_tickets,
            "available_users": available_users,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.get("/projects/{project_id}/edit")
async def edit_project_form(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(["super_admin", "admin", "project_manager"])),
    ],
):
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.department),
            selectinload(Project.owner),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    dept_result = await db.execute(select(Department).order_by(Department.name))
    departments = dept_result.scalars().all()

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "projects/form.html",
        context={
            "current_user": current_user,
            "project": project,
            "departments": departments,
            "errors": [],
            "form_data": None,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.post("/projects/{project_id}/edit")
async def edit_project(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(["super_admin", "admin", "project_manager"])),
    ],
    name: str = Form(""),
    key: str = Form(""),
    description: str = Form(""),
    department_id: str = Form(""),
    status: str = Form(""),
):
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.department),
            selectinload(Project.owner),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    errors = []
    name = name.strip()
    description = description.strip()

    if not name:
        errors.append("Project name is required.")

    valid_statuses = ["planning", "active", "on_hold", "completed", "archived"]
    if status and status not in valid_statuses:
        errors.append(f"Invalid status: {status}")

    form_data = {
        "name": name,
        "key": project.key,
        "description": description,
        "department_id": department_id,
        "status": status,
    }

    if errors:
        dept_result = await db.execute(select(Department).order_by(Department.name))
        departments = dept_result.scalars().all()
        return templates.TemplateResponse(
            request,
            "projects/form.html",
            context={
                "current_user": current_user,
                "project": project,
                "departments": departments,
                "errors": errors,
                "form_data": form_data,
                "flash_messages": [],
            },
        )

    changes = {}
    if name != project.name:
        changes["name"] = {"old": project.name, "new": name}
        project.name = name
    if description != (project.description or ""):
        changes["description"] = {"old": project.description, "new": description}
        project.description = description if description else None
    new_dept_id = department_id if department_id else None
    if new_dept_id != project.department_id:
        changes["department_id"] = {"old": project.department_id, "new": new_dept_id}
        project.department_id = new_dept_id
    if status and status != project.status:
        changes["status"] = {"old": project.status, "new": status}
        project.status = status

    project.updated_at = datetime.utcnow()

    if changes:
        await _log_audit(
            db,
            actor_id=current_user.id,
            action="update",
            entity_type="project",
            entity_id=project.id,
            changes=json.dumps(changes),
        )

    await db.flush()

    response = RedirectResponse(
        url=f"/projects/{project.id}", status_code=303
    )
    set_flash(response, f"Project '{project.name}' updated successfully.", "success")
    return response


@router.post("/projects/{project_id}/delete")
async def delete_project(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(["super_admin", "admin"])),
    ],
):
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_name = project.name

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="delete",
        entity_type="project",
        entity_id=project.id,
        changes=json.dumps({"name": project_name, "key": project.key}),
    )

    await db.delete(project)
    await db.flush()

    response = RedirectResponse(url="/projects", status_code=303)
    set_flash(response, f"Project '{project_name}' deleted.", "success")
    return response


@router.post("/projects/{project_id}/status")
async def change_project_status(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(["super_admin", "admin", "project_manager"])),
    ],
    status: str = Form(""),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    valid_statuses = ["planning", "active", "on_hold", "completed", "archived"]
    if status not in valid_statuses:
        response = RedirectResponse(
            url=f"/projects/{project_id}", status_code=303
        )
        set_flash(response, f"Invalid status: {status}", "error")
        return response

    old_status = project.status
    project.status = status
    project.updated_at = datetime.utcnow()

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="update",
        entity_type="project",
        entity_id=project.id,
        changes=json.dumps({"status": {"old": old_status, "new": status}}),
    )

    await db.flush()

    response = RedirectResponse(
        url=f"/projects/{project_id}", status_code=303
    )
    set_flash(
        response,
        f"Project status changed from '{old_status}' to '{status}'.",
        "success",
    )
    return response


@router.post("/projects/{project_id}/members/add")
async def add_project_member(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(["super_admin", "admin", "project_manager"])),
    ],
    user_id: str = Form(""),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not user_id:
        response = RedirectResponse(
            url=f"/projects/{project_id}", status_code=303
        )
        set_flash(response, "Please select a user to add.", "error")
        return response

    user_result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        response = RedirectResponse(
            url=f"/projects/{project_id}", status_code=303
        )
        set_flash(response, "User not found or inactive.", "error")
        return response

    existing = await db.execute(
        select(project_members).where(
            project_members.c.project_id == project_id,
            project_members.c.user_id == user_id,
        )
    )
    if existing.first():
        response = RedirectResponse(
            url=f"/projects/{project_id}", status_code=303
        )
        set_flash(
            response,
            f"'{user.username}' is already a member of this project.",
            "warning",
        )
        return response

    stmt = project_members.insert().values(
        project_id=project_id,
        user_id=user_id,
    )
    await db.execute(stmt)

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="update",
        entity_type="project",
        entity_id=project_id,
        changes=json.dumps({"member_added": user.username}),
    )

    await db.flush()

    response = RedirectResponse(
        url=f"/projects/{project_id}", status_code=303
    )
    set_flash(
        response,
        f"'{user.username}' added to the project.",
        "success",
    )
    return response


@router.post("/projects/{project_id}/members/remove")
async def remove_project_member(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(["super_admin", "admin", "project_manager"])),
    ],
    user_id: str = Form(""),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not user_id:
        response = RedirectResponse(
            url=f"/projects/{project_id}", status_code=303
        )
        set_flash(response, "No user specified.", "error")
        return response

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    username = user.username if user else "Unknown"

    existing = await db.execute(
        select(project_members).where(
            project_members.c.project_id == project_id,
            project_members.c.user_id == user_id,
        )
    )
    if not existing.first():
        response = RedirectResponse(
            url=f"/projects/{project_id}", status_code=303
        )
        set_flash(response, "User is not a member of this project.", "warning")
        return response

    stmt = project_members.delete().where(
        project_members.c.project_id == project_id,
        project_members.c.user_id == user_id,
    )
    await db.execute(stmt)

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="update",
        entity_type="project",
        entity_id=project_id,
        changes=json.dumps({"member_removed": username}),
    )

    await db.flush()

    response = RedirectResponse(
        url=f"/projects/{project_id}", status_code=303
    )
    set_flash(
        response,
        f"'{username}' removed from the project.",
        "success",
    )
    return response


@router.get("/projects/{project_id}/board")
async def kanban_board(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    assignee_id: str = "",
    sprint_id: str = "",
    label: str = "",
):
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.members),
            selectinload(Project.sprints),
            selectinload(Project.labels),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    ticket_query = (
        select(Ticket)
        .where(Ticket.project_id == project_id)
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.labels),
            selectinload(Ticket.sprint),
        )
    )

    if assignee_id:
        ticket_query = ticket_query.where(Ticket.assignee_id == assignee_id)

    if sprint_id:
        ticket_query = ticket_query.where(Ticket.sprint_id == sprint_id)

    ticket_result = await db.execute(ticket_query)
    all_tickets = ticket_result.scalars().unique().all()

    if label:
        filtered_tickets = []
        for t in all_tickets:
            ticket_label_names = [lb.name for lb in (t.labels or [])]
            if label in ticket_label_names:
                filtered_tickets.append(t)
        all_tickets = filtered_tickets

    statuses = ["backlog", "todo", "in_progress", "in_review", "done", "cancelled"]
    board: dict[str, list] = {s: [] for s in statuses}
    for t in all_tickets:
        ticket_status = t.status or "backlog"
        if ticket_status in board:
            board[ticket_status].append(t)
        else:
            board["backlog"].append(t)

    members = project.members or []
    sprints = project.sprints or []

    label_names_result = await db.execute(
        select(Label.name)
        .where(Label.project_id == project_id)
        .order_by(Label.name)
    )
    label_names = [row[0] for row in label_names_result.all()]

    active_sprint = None
    for s in sprints:
        if s.status == "active":
            active_sprint = s
            break

    filters = {
        "assignee_id": assignee_id,
        "sprint_id": sprint_id,
        "label": label,
    }

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "projects/board.html",
        context={
            "current_user": current_user,
            "project": project,
            "board": board,
            "members": members,
            "sprints": sprints,
            "labels": label_names,
            "sprint": active_sprint,
            "filters": filters,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response