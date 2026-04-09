import json
import logging
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
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
    set_flash,
)
from models.audit_log import AuditLog
from models.comment import Comment
from models.label import Label
from models.project import Project, project_members
from models.sprint import Sprint
from models.ticket import Ticket, ticket_labels
from models.time_entry import TimeEntry
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


async def _check_project_access(
    project_id: str,
    current_user: User,
    db: AsyncSession,
) -> Project:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.department),
            selectinload(Project.owner),
            selectinload(Project.members),
            selectinload(Project.sprints),
            selectinload(Project.labels),
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if current_user.role in ["super_admin", "admin"]:
        return project

    if project.owner_id == current_user.id:
        return project

    member_result = await db.execute(
        select(project_members).where(
            project_members.c.project_id == project_id,
            project_members.c.user_id == current_user.id,
        )
    )
    if member_result.first() is None:
        raise HTTPException(status_code=403, detail="You are not a member of this project.")

    return project


async def _log_audit(
    db: AsyncSession,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
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


# ---------------------------------------------------------------------------
# Ticket List — GET /projects/{project_id}/tickets
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/tickets")
async def list_tickets(
    request: Request,
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str = "",
    status: str = "",
    type: str = "",
    priority: str = "",
    assignee_id: str = "",
    sprint_id: str = "",
    sort: str = "created_desc",
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    project = await _check_project_access(project_id, current_user, db)

    query = select(Ticket).where(Ticket.project_id == project_id).options(
        selectinload(Ticket.assignee),
        selectinload(Ticket.reporter),
        selectinload(Ticket.sprint),
        selectinload(Ticket.labels),
        selectinload(Ticket.project),
    )

    if search:
        query = query.where(
            Ticket.title.ilike(f"%{search}%") | Ticket.description.ilike(f"%{search}%")
        )
    if status:
        query = query.where(Ticket.status == status)
    if type:
        query = query.where(Ticket.type == type)
    if priority:
        query = query.where(Ticket.priority == priority)
    if assignee_id:
        query = query.where(Ticket.assignee_id == assignee_id)
    if sprint_id:
        query = query.where(Ticket.sprint_id == sprint_id)

    if sort == "created_asc":
        query = query.order_by(Ticket.created_at.asc())
    elif sort == "priority_desc":
        query = query.order_by(Ticket.priority.asc())
    elif sort == "priority_asc":
        query = query.order_by(Ticket.priority.desc())
    elif sort == "title_asc":
        query = query.order_by(Ticket.title.asc())
    elif sort == "title_desc":
        query = query.order_by(Ticket.title.desc())
    else:
        query = query.order_by(Ticket.created_at.desc())

    count_query = select(func.count()).select_from(
        query.with_only_columns(Ticket.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    tickets = list(result.scalars().all())

    members_result = await db.execute(
        select(User)
        .join(project_members, project_members.c.user_id == User.id)
        .where(project_members.c.project_id == project_id)
    )
    assignees = list(members_result.scalars().all())

    sprints_result = await db.execute(
        select(Sprint).where(Sprint.project_id == project_id).order_by(Sprint.created_at.desc())
    )
    sprints = list(sprints_result.scalars().all())

    filters = {
        "search": search,
        "status": status,
        "type": type,
        "priority": priority,
        "assignee_id": assignee_id,
        "sprint_id": sprint_id,
        "sort": sort,
    }

    flash_messages = get_flash(request)
    resp = templates.TemplateResponse(
        request,
        "tickets/list.html",
        context={
            "current_user": current_user,
            "project": project,
            "tickets": tickets,
            "filters": filters,
            "assignees": assignees,
            "sprints": sprints,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(resp)
    return resp


# ---------------------------------------------------------------------------
# Global Ticket List — GET /tickets
# ---------------------------------------------------------------------------
@router.get("/tickets")
async def list_all_tickets(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str = "",
    status: str = "",
    type: str = "",
    priority: str = "",
    assignee_id: str = "",
    sprint_id: str = "",
    sort: str = "created_desc",
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    query = select(Ticket).options(
        selectinload(Ticket.assignee),
        selectinload(Ticket.reporter),
        selectinload(Ticket.sprint),
        selectinload(Ticket.labels),
        selectinload(Ticket.project),
    )

    if current_user.role not in ["super_admin", "admin"]:
        accessible_project_ids_q = select(project_members.c.project_id).where(
            project_members.c.user_id == current_user.id
        )
        owned_project_ids_q = select(Project.id).where(Project.owner_id == current_user.id)
        query = query.where(
            Ticket.project_id.in_(accessible_project_ids_q)
            | Ticket.project_id.in_(owned_project_ids_q)
        )

    if search:
        query = query.where(
            Ticket.title.ilike(f"%{search}%") | Ticket.description.ilike(f"%{search}%")
        )
    if status:
        query = query.where(Ticket.status == status)
    if type:
        query = query.where(Ticket.type == type)
    if priority:
        query = query.where(Ticket.priority == priority)
    if assignee_id:
        query = query.where(Ticket.assignee_id == assignee_id)
    if sprint_id:
        query = query.where(Ticket.sprint_id == sprint_id)

    if sort == "created_asc":
        query = query.order_by(Ticket.created_at.asc())
    elif sort == "priority_desc":
        query = query.order_by(Ticket.priority.asc())
    elif sort == "priority_asc":
        query = query.order_by(Ticket.priority.desc())
    elif sort == "title_asc":
        query = query.order_by(Ticket.title.asc())
    elif sort == "title_desc":
        query = query.order_by(Ticket.title.desc())
    else:
        query = query.order_by(Ticket.created_at.desc())

    count_query = select(func.count()).select_from(
        query.with_only_columns(Ticket.id).subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    tickets = list(result.scalars().all())

    users_result = await db.execute(select(User).where(User.is_active == True))
    assignees = list(users_result.scalars().all())

    sprints_result = await db.execute(
        select(Sprint).order_by(Sprint.created_at.desc()).limit(50)
    )
    sprints = list(sprints_result.scalars().all())

    filters = {
        "search": search,
        "status": status,
        "type": type,
        "priority": priority,
        "assignee_id": assignee_id,
        "sprint_id": sprint_id,
        "sort": sort,
    }

    flash_messages = get_flash(request)
    resp = templates.TemplateResponse(
        request,
        "tickets/list.html",
        context={
            "current_user": current_user,
            "project": None,
            "tickets": tickets,
            "filters": filters,
            "assignees": assignees,
            "sprints": sprints,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(resp)
    return resp


# ---------------------------------------------------------------------------
# Create Ticket — GET + POST /projects/{project_id}/tickets/create
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/tickets/create")
async def create_ticket_form(
    request: Request,
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    project = await _check_project_access(project_id, current_user, db)

    members_result = await db.execute(
        select(User)
        .join(project_members, project_members.c.user_id == User.id)
        .where(project_members.c.project_id == project_id)
    )
    members = list(members_result.scalars().all())

    sprints_result = await db.execute(
        select(Sprint).where(Sprint.project_id == project_id).order_by(Sprint.created_at.desc())
    )
    sprints = list(sprints_result.scalars().all())

    tickets_result = await db.execute(
        select(Ticket).where(Ticket.project_id == project_id).order_by(Ticket.title.asc())
    )
    available_tickets = list(tickets_result.scalars().all())

    labels_result = await db.execute(
        select(Label).where(Label.project_id == project_id).order_by(Label.name.asc())
    )
    available_labels = [label.name for label in labels_result.scalars().all()]

    flash_messages = get_flash(request)
    resp = templates.TemplateResponse(
        request,
        "tickets/form.html",
        context={
            "current_user": current_user,
            "project": project,
            "ticket": None,
            "members": members,
            "sprints": sprints,
            "available_tickets": available_tickets,
            "available_labels": available_labels,
            "form_data": None,
            "errors": None,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(resp)
    return resp


@router.post("/projects/{project_id}/tickets/create")
async def create_ticket(
    request: Request,
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    title: str = Form(""),
    description: str = Form(""),
    ticket_type: str = Form("task"),
    priority: str = Form("medium"),
    status: str = Form("backlog"),
    story_points: str = Form(""),
    assignee_id: str = Form(""),
    sprint_id: str = Form(""),
    parent_id: str = Form(""),
):
    project = await _check_project_access(project_id, current_user, db)

    form_data_raw = await request.form()
    label_values = form_data_raw.getlist("labels")

    form_data = {
        "title": title,
        "description": description,
        "ticket_type": ticket_type,
        "priority": priority,
        "status": status,
        "story_points": story_points,
        "assignee_id": assignee_id,
        "sprint_id": sprint_id,
        "parent_id": parent_id,
        "labels": label_values,
    }

    errors = []
    if not title or not title.strip():
        errors.append("Title is required.")
    if len(title) > 200:
        errors.append("Title must be 200 characters or fewer.")

    valid_types = ["feature", "bug", "task", "improvement"]
    if ticket_type not in valid_types:
        errors.append(f"Type must be one of: {', '.join(valid_types)}.")

    valid_priorities = ["critical", "high", "medium", "low"]
    if priority not in valid_priorities:
        errors.append(f"Priority must be one of: {', '.join(valid_priorities)}.")

    valid_statuses = ["backlog", "todo", "in_progress", "in_review", "done", "closed", "cancelled"]
    if status not in valid_statuses:
        errors.append(f"Status must be one of: {', '.join(valid_statuses)}.")

    sp_value = None
    if story_points and story_points.strip():
        try:
            sp_value = int(story_points)
            if sp_value < 0 or sp_value > 100:
                errors.append("Story points must be between 0 and 100.")
        except ValueError:
            errors.append("Story points must be a valid integer.")

    if errors:
        members_result = await db.execute(
            select(User)
            .join(project_members, project_members.c.user_id == User.id)
            .where(project_members.c.project_id == project_id)
        )
        members = list(members_result.scalars().all())
        sprints_result = await db.execute(
            select(Sprint).where(Sprint.project_id == project_id)
        )
        sprints = list(sprints_result.scalars().all())
        tickets_result = await db.execute(
            select(Ticket).where(Ticket.project_id == project_id)
        )
        available_tickets = list(tickets_result.scalars().all())
        labels_result = await db.execute(
            select(Label).where(Label.project_id == project_id)
        )
        available_labels = [l.name for l in labels_result.scalars().all()]

        return templates.TemplateResponse(
            request,
            "tickets/form.html",
            context={
                "current_user": current_user,
                "project": project,
                "ticket": None,
                "members": members,
                "sprints": sprints,
                "available_tickets": available_tickets,
                "available_labels": available_labels,
                "form_data": form_data,
                "errors": errors,
                "flash_messages": [],
            },
            status_code=422,
        )

    ticket = Ticket(
        id=str(uuid.uuid4()),
        project_id=project_id,
        title=title.strip(),
        description=description.strip() if description else None,
        type=ticket_type,
        priority=priority,
        status=status,
        story_points=sp_value,
        assignee_id=assignee_id if assignee_id else None,
        sprint_id=sprint_id if sprint_id else None,
        parent_id=parent_id if parent_id else None,
        reporter_id=current_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(ticket)
    await db.flush()

    if label_values:
        for label_name in label_values:
            label_result = await db.execute(
                select(Label).where(
                    Label.project_id == project_id,
                    Label.name == label_name,
                )
            )
            label = label_result.scalar_one_or_none()
            if label:
                await db.execute(
                    ticket_labels.insert().values(
                        ticket_id=ticket.id,
                        label_id=label.id,
                    )
                )

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="create",
        entity_type="ticket",
        entity_id=ticket.id,
        changes=json.dumps({"title": ticket.title, "type": ticket_type, "priority": priority}),
    )

    logger.info("Ticket '%s' created by user '%s' in project '%s'.", ticket.title, current_user.username, project_id)

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket.id}",
        status_code=303,
    )
    set_flash(response, "Ticket created successfully.", "success")
    return response


# ---------------------------------------------------------------------------
# Ticket Detail — GET /projects/{project_id}/tickets/{ticket_id}
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/tickets/{ticket_id}")
async def ticket_detail(
    request: Request,
    project_id: str,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    project = await _check_project_access(project_id, current_user, db)

    result = await db.execute(
        select(Ticket)
        .where(Ticket.id == ticket_id, Ticket.project_id == project_id)
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.reporter),
            selectinload(Ticket.sprint),
            selectinload(Ticket.labels),
            selectinload(Ticket.project).selectinload(Project.department),
            selectinload(Ticket.parent),
            selectinload(Ticket.children).selectinload(Ticket.assignee),
            selectinload(Ticket.comments).selectinload(Comment.user),
            selectinload(Ticket.comments).selectinload(Comment.replies).selectinload(Comment.user),
            selectinload(Ticket.time_entries).selectinload(TimeEntry.user),
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.identifier = f"{project.key}-{ticket.id[:8].upper()}" if project.key else f"#{ticket.id[:8]}"

    top_level_comments = [c for c in ticket.comments if c.parent_id is None]

    subtasks = ticket.children if ticket.children else []
    for st in subtasks:
        st.identifier = f"{project.key}-{st.id[:8].upper()}" if project.key else f"#{st.id[:8]}"

    total_hours = sum(e.hours for e in ticket.time_entries) if ticket.time_entries else 0.0
    total_billable_hours = sum(
        e.hours for e in ticket.time_entries if e.billable
    ) if ticket.time_entries else 0.0

    flash_messages = get_flash(request)
    resp = templates.TemplateResponse(
        request,
        "tickets/detail.html",
        context={
            "current_user": current_user,
            "project": project,
            "ticket": ticket,
            "comments": top_level_comments,
            "subtasks": subtasks,
            "time_entries": ticket.time_entries or [],
            "total_hours": total_hours,
            "total_billable_hours": total_billable_hours,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(resp)
    return resp


# ---------------------------------------------------------------------------
# Ticket Detail (global) — GET /tickets/{ticket_id}
# ---------------------------------------------------------------------------
@router.get("/tickets/{ticket_id}")
async def ticket_detail_global(
    request: Request,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id).options(
            selectinload(Ticket.project),
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return RedirectResponse(
        url=f"/projects/{ticket.project_id}/tickets/{ticket.id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Edit Ticket — GET + POST /projects/{project_id}/tickets/{ticket_id}/edit
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/tickets/{ticket_id}/edit")
async def edit_ticket_form(
    request: Request,
    project_id: str,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    project = await _check_project_access(project_id, current_user, db)

    result = await db.execute(
        select(Ticket)
        .where(Ticket.id == ticket_id, Ticket.project_id == project_id)
        .options(
            selectinload(Ticket.assignee),
            selectinload(Ticket.labels),
            selectinload(Ticket.sprint),
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user.role not in ["super_admin", "admin", "project_manager", "team_lead"]:
        if ticket.assignee_id != current_user.id and ticket.reporter_id != current_user.id:
            raise HTTPException(status_code=403, detail="Insufficient permissions to edit this ticket.")

    members_result = await db.execute(
        select(User)
        .join(project_members, project_members.c.user_id == User.id)
        .where(project_members.c.project_id == project_id)
    )
    members = list(members_result.scalars().all())

    sprints_result = await db.execute(
        select(Sprint).where(Sprint.project_id == project_id).order_by(Sprint.created_at.desc())
    )
    sprints = list(sprints_result.scalars().all())

    tickets_result = await db.execute(
        select(Ticket).where(Ticket.project_id == project_id, Ticket.id != ticket_id)
    )
    available_tickets = list(tickets_result.scalars().all())

    labels_result = await db.execute(
        select(Label).where(Label.project_id == project_id).order_by(Label.name.asc())
    )
    available_labels = [l.name for l in labels_result.scalars().all()]

    form_data = {
        "title": ticket.title,
        "description": ticket.description or "",
        "ticket_type": ticket.type,
        "priority": ticket.priority,
        "status": ticket.status,
        "story_points": str(ticket.story_points) if ticket.story_points is not None else "",
        "assignee_id": ticket.assignee_id or "",
        "sprint_id": ticket.sprint_id or "",
        "parent_id": ticket.parent_id or "",
        "labels": [l.name for l in ticket.labels] if ticket.labels else [],
    }

    flash_messages = get_flash(request)
    resp = templates.TemplateResponse(
        request,
        "tickets/form.html",
        context={
            "current_user": current_user,
            "project": project,
            "ticket": ticket,
            "members": members,
            "sprints": sprints,
            "available_tickets": available_tickets,
            "available_labels": available_labels,
            "form_data": form_data,
            "errors": None,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(resp)
    return resp


@router.get("/tickets/{ticket_id}/edit")
async def edit_ticket_form_global(
    request: Request,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return RedirectResponse(
        url=f"/projects/{ticket.project_id}/tickets/{ticket.id}/edit",
        status_code=303,
    )


@router.post("/projects/{project_id}/tickets/{ticket_id}/edit")
async def edit_ticket(
    request: Request,
    project_id: str,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    title: str = Form(""),
    description: str = Form(""),
    ticket_type: str = Form("task"),
    priority: str = Form("medium"),
    status: str = Form("backlog"),
    story_points: str = Form(""),
    assignee_id: str = Form(""),
    sprint_id: str = Form(""),
    parent_id: str = Form(""),
):
    project = await _check_project_access(project_id, current_user, db)

    result = await db.execute(
        select(Ticket)
        .where(Ticket.id == ticket_id, Ticket.project_id == project_id)
        .options(selectinload(Ticket.labels))
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user.role not in ["super_admin", "admin", "project_manager", "team_lead"]:
        if ticket.assignee_id != current_user.id and ticket.reporter_id != current_user.id:
            raise HTTPException(status_code=403, detail="Insufficient permissions to edit this ticket.")

    form_data_raw = await request.form()
    label_values = form_data_raw.getlist("labels")

    form_data = {
        "title": title,
        "description": description,
        "ticket_type": ticket_type,
        "priority": priority,
        "status": status,
        "story_points": story_points,
        "assignee_id": assignee_id,
        "sprint_id": sprint_id,
        "parent_id": parent_id,
        "labels": label_values,
    }

    errors = []
    if not title or not title.strip():
        errors.append("Title is required.")
    if len(title) > 200:
        errors.append("Title must be 200 characters or fewer.")

    valid_types = ["feature", "bug", "task", "improvement"]
    if ticket_type not in valid_types:
        errors.append(f"Type must be one of: {', '.join(valid_types)}.")

    valid_priorities = ["critical", "high", "medium", "low"]
    if priority not in valid_priorities:
        errors.append(f"Priority must be one of: {', '.join(valid_priorities)}.")

    valid_statuses = ["backlog", "todo", "in_progress", "in_review", "done", "closed", "cancelled"]
    if status not in valid_statuses:
        errors.append(f"Status must be one of: {', '.join(valid_statuses)}.")

    sp_value = None
    if story_points and story_points.strip():
        try:
            sp_value = int(story_points)
            if sp_value < 0 or sp_value > 100:
                errors.append("Story points must be between 0 and 100.")
        except ValueError:
            errors.append("Story points must be a valid integer.")

    if errors:
        members_result = await db.execute(
            select(User)
            .join(project_members, project_members.c.user_id == User.id)
            .where(project_members.c.project_id == project_id)
        )
        members = list(members_result.scalars().all())
        sprints_result = await db.execute(
            select(Sprint).where(Sprint.project_id == project_id)
        )
        sprints = list(sprints_result.scalars().all())
        tickets_result = await db.execute(
            select(Ticket).where(Ticket.project_id == project_id, Ticket.id != ticket_id)
        )
        available_tickets = list(tickets_result.scalars().all())
        labels_result = await db.execute(
            select(Label).where(Label.project_id == project_id)
        )
        available_labels = [l.name for l in labels_result.scalars().all()]

        return templates.TemplateResponse(
            request,
            "tickets/form.html",
            context={
                "current_user": current_user,
                "project": project,
                "ticket": ticket,
                "members": members,
                "sprints": sprints,
                "available_tickets": available_tickets,
                "available_labels": available_labels,
                "form_data": form_data,
                "errors": errors,
                "flash_messages": [],
            },
            status_code=422,
        )

    changes = {}
    if ticket.title != title.strip():
        changes["title"] = {"old": ticket.title, "new": title.strip()}
    if ticket.status != status:
        changes["status"] = {"old": ticket.status, "new": status}
    if ticket.priority != priority:
        changes["priority"] = {"old": ticket.priority, "new": priority}
    if ticket.type != ticket_type:
        changes["type"] = {"old": ticket.type, "new": ticket_type}

    ticket.title = title.strip()
    ticket.description = description.strip() if description else None
    ticket.type = ticket_type
    ticket.priority = priority
    ticket.status = status
    ticket.story_points = sp_value
    ticket.assignee_id = assignee_id if assignee_id else None
    ticket.sprint_id = sprint_id if sprint_id else None
    ticket.parent_id = parent_id if parent_id else None
    ticket.updated_at = datetime.utcnow()

    await db.execute(
        ticket_labels.delete().where(ticket_labels.c.ticket_id == ticket_id)
    )
    if label_values:
        for label_name in label_values:
            label_result = await db.execute(
                select(Label).where(
                    Label.project_id == project_id,
                    Label.name == label_name,
                )
            )
            label = label_result.scalar_one_or_none()
            if label:
                await db.execute(
                    ticket_labels.insert().values(
                        ticket_id=ticket.id,
                        label_id=label.id,
                    )
                )

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="update",
        entity_type="ticket",
        entity_id=ticket.id,
        changes=json.dumps(changes) if changes else None,
    )

    logger.info("Ticket '%s' updated by user '%s'.", ticket.title, current_user.username)

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket.id}",
        status_code=303,
    )
    set_flash(response, "Ticket updated successfully.", "success")
    return response


# ---------------------------------------------------------------------------
# Delete Ticket — POST /projects/{project_id}/tickets/{ticket_id}/delete
#                  POST /tickets/{ticket_id}/delete
# ---------------------------------------------------------------------------
@router.post("/projects/{project_id}/tickets/{ticket_id}/delete")
async def delete_ticket(
    request: Request,
    project_id: str,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role not in ["super_admin", "admin", "project_manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to delete tickets.")

    project = await _check_project_access(project_id, current_user, db)

    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.project_id == project_id)
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket_title = ticket.title

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="delete",
        entity_type="ticket",
        entity_id=ticket.id,
        changes=json.dumps({"title": ticket_title}),
    )

    await db.delete(ticket)

    logger.info("Ticket '%s' deleted by user '%s'.", ticket_title, current_user.username)

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets",
        status_code=303,
    )
    set_flash(response, f"Ticket '{ticket_title}' deleted.", "success")
    return response


@router.post("/tickets/{ticket_id}/delete")
async def delete_ticket_global(
    request: Request,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role not in ["super_admin", "admin", "project_manager"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to delete tickets.")

    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    project_id = ticket.project_id
    ticket_title = ticket.title

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="delete",
        entity_type="ticket",
        entity_id=ticket.id,
        changes=json.dumps({"title": ticket_title}),
    )

    await db.delete(ticket)

    logger.info("Ticket '%s' deleted by user '%s'.", ticket_title, current_user.username)

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets",
        status_code=303,
    )
    set_flash(response, f"Ticket '{ticket_title}' deleted.", "success")
    return response


# ---------------------------------------------------------------------------
# Status Transition — POST /tickets/{ticket_id}/transition
#                     POST /tickets/{ticket_id}/status
#                     PATCH /projects/{project_id}/tickets/{ticket_id}/status
# ---------------------------------------------------------------------------
@router.post("/tickets/{ticket_id}/transition")
async def transition_ticket_status(
    request: Request,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str = Form(""),
):
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id).options(
            selectinload(Ticket.project),
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user.role not in ["super_admin", "admin", "project_manager", "team_lead"]:
        if ticket.assignee_id != current_user.id:
            raise HTTPException(status_code=403, detail="Insufficient permissions to change ticket status.")

    valid_statuses = ["backlog", "todo", "in_progress", "in_review", "done", "closed", "cancelled"]
    if status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid status: {status}")

    old_status = ticket.status
    ticket.status = status
    ticket.updated_at = datetime.utcnow()

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="update",
        entity_type="ticket",
        entity_id=ticket.id,
        changes=json.dumps({"status": {"old": old_status, "new": status}}),
    )

    logger.info(
        "Ticket '%s' status changed from '%s' to '%s' by user '%s'.",
        ticket.title, old_status, status, current_user.username,
    )

    response = RedirectResponse(
        url=f"/projects/{ticket.project_id}/tickets/{ticket.id}",
        status_code=303,
    )
    set_flash(response, f"Ticket status changed to {status.replace('_', ' ').title()}.", "success")
    return response


@router.post("/tickets/{ticket_id}/status")
async def change_ticket_status_post(
    request: Request,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str = Form(""),
):
    return await transition_ticket_status(request, ticket_id, current_user, db, status)


from fastapi import Body


@router.patch("/projects/{project_id}/tickets/{ticket_id}/status")
async def change_ticket_status_api(
    project_id: str,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: dict = Body(...),
):
    new_status = body.get("status", "")

    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.project_id == project_id)
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user.role not in ["super_admin", "admin", "project_manager", "team_lead"]:
        if ticket.assignee_id != current_user.id:
            raise HTTPException(status_code=403, detail="Insufficient permissions.")

    valid_statuses = ["backlog", "todo", "in_progress", "in_review", "done", "closed", "cancelled"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid status: {new_status}")

    old_status = ticket.status
    ticket.status = new_status
    ticket.updated_at = datetime.utcnow()

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="update",
        entity_type="ticket",
        entity_id=ticket.id,
        changes=json.dumps({"status": {"old": old_status, "new": new_status}}),
    )

    return {"id": ticket.id, "status": ticket.status}


# ---------------------------------------------------------------------------
# Comments — POST /tickets/{ticket_id}/comments
# ---------------------------------------------------------------------------
@router.post("/tickets/{ticket_id}/comments")
async def add_comment(
    request: Request,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    content: str = Form(""),
    is_internal: str = Form(""),
    parent_comment_id: str = Form(""),
):
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id).options(
            selectinload(Ticket.project),
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if not content or not content.strip():
        response = RedirectResponse(
            url=f"/projects/{ticket.project_id}/tickets/{ticket.id}",
            status_code=303,
        )
        set_flash(response, "Comment content cannot be empty.", "error")
        return response

    internal_flag = is_internal.lower() in ("true", "on", "1", "yes") if is_internal else False

    comment = Comment(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        author_id=current_user.id,
        content=content.strip(),
        is_internal=internal_flag,
        parent_id=parent_comment_id if parent_comment_id else None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(comment)

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="create",
        entity_type="comment",
        entity_id=comment.id,
        changes=json.dumps({"ticket_id": ticket_id, "is_internal": internal_flag}),
    )

    logger.info("Comment added to ticket '%s' by user '%s'.", ticket.title, current_user.username)

    response = RedirectResponse(
        url=f"/projects/{ticket.project_id}/tickets/{ticket.id}#comment-{comment.id}",
        status_code=303,
    )
    set_flash(response, "Comment added.", "success")
    return response


# ---------------------------------------------------------------------------
# Delete Comment — POST /tickets/{ticket_id}/comments/{comment_id}/delete
# ---------------------------------------------------------------------------
@router.post("/tickets/{ticket_id}/comments/{comment_id}/delete")
async def delete_comment(
    request: Request,
    ticket_id: str,
    comment_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Comment).where(Comment.id == comment_id, Comment.ticket_id == ticket_id)
    )
    comment = result.scalar_one_or_none()
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    if current_user.role not in ["super_admin", "admin"] and comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Insufficient permissions to delete this comment.")

    ticket_result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = ticket_result.scalar_one_or_none()
    project_id = ticket.project_id if ticket else ""

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="delete",
        entity_type="comment",
        entity_id=comment.id,
        changes=json.dumps({"ticket_id": ticket_id}),
    )

    await db.delete(comment)

    logger.info("Comment '%s' deleted by user '%s'.", comment_id, current_user.username)

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket_id}",
        status_code=303,
    )
    set_flash(response, "Comment deleted.", "success")
    return response


# ---------------------------------------------------------------------------
# Time Entries — POST /tickets/{ticket_id}/time-entries
# ---------------------------------------------------------------------------
@router.post("/tickets/{ticket_id}/time-entries")
async def add_time_entry(
    request: Request,
    ticket_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    hours: str = Form(""),
    date_str: str = Form("", alias="date"),
    description: str = Form(""),
    billable: str = Form(""),
):
    form_data_raw = await request.form()
    date_val = form_data_raw.get("date", "")

    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id).options(
            selectinload(Ticket.project),
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    errors = []
    hours_float = 0.0
    if not hours or not hours.strip():
        errors.append("Hours is required.")
    else:
        try:
            hours_float = float(hours)
            if hours_float <= 0 or hours_float > 24:
                errors.append("Hours must be between 0 and 24.")
        except ValueError:
            errors.append("Hours must be a valid number.")

    entry_date = None
    if not date_val:
        errors.append("Date is required.")
    else:
        try:
            entry_date = date.fromisoformat(str(date_val))
        except (ValueError, TypeError):
            errors.append("Date must be a valid date (YYYY-MM-DD).")

    if errors:
        response = RedirectResponse(
            url=f"/projects/{ticket.project_id}/tickets/{ticket.id}",
            status_code=303,
        )
        set_flash(response, " ".join(errors), "error")
        return response

    billable_flag = billable.lower() in ("true", "on", "1", "yes") if billable else False

    time_entry = TimeEntry(
        id=str(uuid.uuid4()),
        ticket_id=ticket_id,
        user_id=current_user.id,
        hours=hours_float,
        description=description.strip() if description else None,
        date=entry_date,
        billable=billable_flag,
        created_at=datetime.utcnow(),
    )
    db.add(time_entry)

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="create",
        entity_type="time_entry",
        entity_id=time_entry.id,
        changes=json.dumps({"ticket_id": ticket_id, "hours": hours_float}),
    )

    logger.info(
        "Time entry (%.1fh) added to ticket '%s' by user '%s'.",
        hours_float, ticket.title, current_user.username,
    )

    response = RedirectResponse(
        url=f"/projects/{ticket.project_id}/tickets/{ticket.id}",
        status_code=303,
    )
    set_flash(response, f"Time entry of {hours_float}h logged.", "success")
    return response


# ---------------------------------------------------------------------------
# Delete Time Entry — POST /tickets/{ticket_id}/time-entries/{entry_id}/delete
# ---------------------------------------------------------------------------
@router.post("/tickets/{ticket_id}/time-entries/{entry_id}/delete")
async def delete_time_entry(
    request: Request,
    ticket_id: str,
    entry_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(TimeEntry).where(TimeEntry.id == entry_id, TimeEntry.ticket_id == ticket_id)
    )
    time_entry = result.scalar_one_or_none()
    if time_entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")

    if current_user.role not in ["super_admin", "admin", "project_manager"] and time_entry.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Insufficient permissions to delete this time entry.")

    ticket_result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = ticket_result.scalar_one_or_none()
    project_id = ticket.project_id if ticket else ""

    await _log_audit(
        db,
        actor_id=current_user.id,
        action="delete",
        entity_type="time_entry",
        entity_id=time_entry.id,
        changes=json.dumps({"ticket_id": ticket_id, "hours": time_entry.hours}),
    )

    await db.delete(time_entry)

    logger.info("Time entry '%s' deleted by user '%s'.", entry_id, current_user.username)

    response = RedirectResponse(
        url=f"/projects/{project_id}/tickets/{ticket_id}",
        status_code=303,
    )
    set_flash(response, "Time entry deleted.", "success")
    return response


# ---------------------------------------------------------------------------
# Create Ticket (global redirect) — GET /tickets/create
# ---------------------------------------------------------------------------
@router.get("/tickets/create")
async def create_ticket_global(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: str = Query("", alias="project_id"),
):
    if project_id:
        return RedirectResponse(
            url=f"/projects/{project_id}/tickets/create",
            status_code=303,
        )

    if current_user.role in ["super_admin", "admin"]:
        result = await db.execute(
            select(Project).order_by(Project.name.asc()).limit(1)
        )
    else:
        result = await db.execute(
            select(Project)
            .join(project_members, project_members.c.project_id == Project.id)
            .where(project_members.c.user_id == current_user.id)
            .order_by(Project.name.asc())
            .limit(1)
        )

    project = result.scalar_one_or_none()
    if project is None:
        response = RedirectResponse(url="/projects", status_code=303)
        set_flash(response, "Please select a project first to create a ticket.", "warning")
        return response

    return RedirectResponse(
        url=f"/projects/{project.id}/tickets/create",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# New Ticket shortcut — GET /projects/{project_id}/tickets/new
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/tickets/new")
async def create_ticket_new_redirect(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    return RedirectResponse(
        url=f"/projects/{project_id}/tickets/create",
        status_code=303,
    )