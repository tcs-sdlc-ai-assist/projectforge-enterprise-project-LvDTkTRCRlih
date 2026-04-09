import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from dependencies import (
    get_current_user,
    get_flash,
    clear_flash,
    set_flash,
    get_current_user_optional,
)
from models.audit_log import AuditLog
from models.project import Project
from models.sprint import Sprint
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


async def _get_project_or_404(
    project_id: str,
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
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_sprint_or_404(
    sprint_id: str,
    db: AsyncSession,
) -> Sprint:
    result = await db.execute(
        select(Sprint)
        .where(Sprint.id == sprint_id)
        .options(
            selectinload(Sprint.project),
            selectinload(Sprint.tickets),
        )
    )
    sprint = result.scalar_one_or_none()
    if sprint is None:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint


def _check_sprint_management_role(user: User) -> None:
    allowed_roles = ["super_admin", "admin", "project_manager", "team_lead"]
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to manage sprints.",
        )


async def _log_audit(
    db: AsyncSession,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    changes: str | None = None,
) -> None:
    audit_entry = AuditLog(
        id=str(uuid.uuid4()),
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
        timestamp=datetime.utcnow(),
    )
    db.add(audit_entry)


@router.get("/projects/{project_id}/sprints")
async def list_sprints(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await _get_project_or_404(project_id, db)

    result = await db.execute(
        select(Sprint)
        .where(Sprint.project_id == project_id)
        .options(
            selectinload(Sprint.project),
            selectinload(Sprint.tickets),
        )
        .order_by(Sprint.created_at.desc())
    )
    sprints = list(result.scalars().all())

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "sprints/list.html",
        context={
            "project": project,
            "sprints": sprints,
            "current_user": current_user,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.get("/projects/{project_id}/sprints/create")
async def create_sprint_form(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    _check_sprint_management_role(current_user)
    project = await _get_project_or_404(project_id, db)

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "sprints/form.html",
        context={
            "project": project,
            "sprint": None,
            "errors": [],
            "form_data": None,
            "current_user": current_user,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.post("/projects/{project_id}/sprints/create")
async def create_sprint(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
    goal: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
):
    _check_sprint_management_role(current_user)
    project = await _get_project_or_404(project_id, db)

    errors = []

    if not name or not name.strip():
        errors.append("Sprint name is required.")

    parsed_start_date = None
    parsed_end_date = None

    if start_date and start_date.strip():
        try:
            from datetime import date as date_type
            parsed_start_date = date_type.fromisoformat(start_date.strip())
        except ValueError:
            errors.append("Invalid start date format. Use YYYY-MM-DD.")
    else:
        errors.append("Start date is required.")

    if end_date and end_date.strip():
        try:
            from datetime import date as date_type
            parsed_end_date = date_type.fromisoformat(end_date.strip())
        except ValueError:
            errors.append("Invalid end date format. Use YYYY-MM-DD.")
    else:
        errors.append("End date is required.")

    if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
        errors.append("Start date must be before or equal to end date.")

    if errors:
        flash_messages = get_flash(request)
        return templates.TemplateResponse(
            request,
            "sprints/form.html",
            context={
                "project": project,
                "sprint": None,
                "errors": errors,
                "form_data": {
                    "name": name,
                    "goal": goal,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                "current_user": current_user,
                "flash_messages": flash_messages,
            },
            status_code=422,
        )

    sprint = Sprint(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=name.strip(),
        goal=goal.strip() if goal and goal.strip() else None,
        status="planning",
        start_date=parsed_start_date,
        end_date=parsed_end_date,
    )
    db.add(sprint)
    await db.flush()

    await _log_audit(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="sprint",
        entity_id=sprint.id,
        changes=f"Created sprint '{sprint.name}' for project '{project.name}'",
    )

    logger.info(
        "Sprint '%s' created for project '%s' by user '%s'.",
        sprint.name,
        project.name,
        current_user.username,
    )

    response = RedirectResponse(
        url=f"/projects/{project_id}/sprints",
        status_code=303,
    )
    set_flash(response, f"Sprint '{sprint.name}' created successfully.", "success")
    return response


@router.get("/projects/{project_id}/sprints/{sprint_id}")
async def sprint_detail(
    request: Request,
    project_id: str,
    sprint_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await _get_project_or_404(project_id, db)
    sprint = await _get_sprint_or_404(sprint_id, db)

    if sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found in this project")

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "sprints/list.html",
        context={
            "project": project,
            "sprints": [sprint],
            "current_user": current_user,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.get("/projects/{project_id}/sprints/{sprint_id}/edit")
async def edit_sprint_form(
    request: Request,
    project_id: str,
    sprint_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    _check_sprint_management_role(current_user)
    project = await _get_project_or_404(project_id, db)
    sprint = await _get_sprint_or_404(sprint_id, db)

    if sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found in this project")

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "sprints/form.html",
        context={
            "project": project,
            "sprint": sprint,
            "errors": [],
            "form_data": None,
            "current_user": current_user,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.post("/projects/{project_id}/sprints/{sprint_id}/edit")
async def edit_sprint(
    request: Request,
    project_id: str,
    sprint_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
    goal: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    status: str = Form(""),
):
    _check_sprint_management_role(current_user)
    project = await _get_project_or_404(project_id, db)
    sprint = await _get_sprint_or_404(sprint_id, db)

    if sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found in this project")

    errors = []

    if not name or not name.strip():
        errors.append("Sprint name is required.")

    parsed_start_date = None
    parsed_end_date = None

    if start_date and start_date.strip():
        try:
            from datetime import date as date_type
            parsed_start_date = date_type.fromisoformat(start_date.strip())
        except ValueError:
            errors.append("Invalid start date format. Use YYYY-MM-DD.")
    else:
        errors.append("Start date is required.")

    if end_date and end_date.strip():
        try:
            from datetime import date as date_type
            parsed_end_date = date_type.fromisoformat(end_date.strip())
        except ValueError:
            errors.append("Invalid end date format. Use YYYY-MM-DD.")
    else:
        errors.append("End date is required.")

    if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
        errors.append("Start date must be before or equal to end date.")

    valid_statuses = ["planning", "active", "completed"]
    if status and status not in valid_statuses:
        errors.append(f"Invalid status. Must be one of: {', '.join(valid_statuses)}.")

    if status == "active":
        active_result = await db.execute(
            select(Sprint).where(
                Sprint.project_id == project_id,
                Sprint.status == "active",
                Sprint.id != sprint_id,
            )
        )
        existing_active = active_result.scalar_one_or_none()
        if existing_active is not None:
            errors.append(
                f"Cannot set status to active. Sprint '{existing_active.name}' is already active in this project."
            )

    if errors:
        flash_messages = get_flash(request)
        return templates.TemplateResponse(
            request,
            "sprints/form.html",
            context={
                "project": project,
                "sprint": sprint,
                "errors": errors,
                "form_data": {
                    "name": name,
                    "goal": goal,
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": status,
                },
                "current_user": current_user,
                "flash_messages": flash_messages,
            },
            status_code=422,
        )

    changes = []
    if sprint.name != name.strip():
        changes.append(f"name: '{sprint.name}' → '{name.strip()}'")
        sprint.name = name.strip()

    new_goal = goal.strip() if goal and goal.strip() else None
    if sprint.goal != new_goal:
        changes.append(f"goal updated")
        sprint.goal = new_goal

    if sprint.start_date != parsed_start_date:
        changes.append(f"start_date: '{sprint.start_date}' → '{parsed_start_date}'")
        sprint.start_date = parsed_start_date

    if sprint.end_date != parsed_end_date:
        changes.append(f"end_date: '{sprint.end_date}' → '{parsed_end_date}'")
        sprint.end_date = parsed_end_date

    if status and sprint.status != status:
        changes.append(f"status: '{sprint.status}' → '{status}'")
        sprint.status = status

    sprint.updated_at = datetime.utcnow()

    await db.flush()

    if changes:
        await _log_audit(
            db=db,
            actor_id=current_user.id,
            action="update",
            entity_type="sprint",
            entity_id=sprint.id,
            changes="; ".join(changes),
        )

    logger.info(
        "Sprint '%s' updated by user '%s'.",
        sprint.name,
        current_user.username,
    )

    response = RedirectResponse(
        url=f"/projects/{project_id}/sprints",
        status_code=303,
    )
    set_flash(response, f"Sprint '{sprint.name}' updated successfully.", "success")
    return response


@router.post("/projects/{project_id}/sprints/{sprint_id}/start")
async def start_sprint(
    request: Request,
    project_id: str,
    sprint_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    _check_sprint_management_role(current_user)
    project = await _get_project_or_404(project_id, db)
    sprint = await _get_sprint_or_404(sprint_id, db)

    if sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found in this project")

    if sprint.status != "planning":
        response = RedirectResponse(
            url=f"/projects/{project_id}/sprints",
            status_code=303,
        )
        set_flash(
            response,
            f"Sprint '{sprint.name}' cannot be started because it is currently '{sprint.status}'.",
            "error",
        )
        return response

    active_result = await db.execute(
        select(Sprint).where(
            Sprint.project_id == project_id,
            Sprint.status == "active",
            Sprint.id != sprint_id,
        )
    )
    existing_active = active_result.scalar_one_or_none()
    if existing_active is not None:
        response = RedirectResponse(
            url=f"/projects/{project_id}/sprints",
            status_code=303,
        )
        set_flash(
            response,
            f"Cannot start sprint. Sprint '{existing_active.name}' is already active in this project.",
            "error",
        )
        return response

    old_status = sprint.status
    sprint.status = "active"
    sprint.updated_at = datetime.utcnow()

    await db.flush()

    await _log_audit(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="sprint",
        entity_id=sprint.id,
        changes=f"status: '{old_status}' → 'active'",
    )

    logger.info(
        "Sprint '%s' started by user '%s'.",
        sprint.name,
        current_user.username,
    )

    response = RedirectResponse(
        url=f"/projects/{project_id}/sprints",
        status_code=303,
    )
    set_flash(response, f"Sprint '{sprint.name}' is now active.", "success")
    return response


@router.post("/projects/{project_id}/sprints/{sprint_id}/complete")
async def complete_sprint(
    request: Request,
    project_id: str,
    sprint_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    _check_sprint_management_role(current_user)
    project = await _get_project_or_404(project_id, db)
    sprint = await _get_sprint_or_404(sprint_id, db)

    if sprint.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sprint not found in this project")

    if sprint.status != "active":
        response = RedirectResponse(
            url=f"/projects/{project_id}/sprints",
            status_code=303,
        )
        set_flash(
            response,
            f"Sprint '{sprint.name}' cannot be completed because it is currently '{sprint.status}'.",
            "error",
        )
        return response

    old_status = sprint.status
    sprint.status = "completed"
    sprint.updated_at = datetime.utcnow()

    await db.flush()

    await _log_audit(
        db=db,
        actor_id=current_user.id,
        action="update",
        entity_type="sprint",
        entity_id=sprint.id,
        changes=f"status: '{old_status}' → 'completed'",
    )

    logger.info(
        "Sprint '%s' completed by user '%s'.",
        sprint.name,
        current_user.username,
    )

    response = RedirectResponse(
        url=f"/projects/{project_id}/sprints",
        status_code=303,
    )
    set_flash(response, f"Sprint '{sprint.name}' has been completed.", "success")
    return response