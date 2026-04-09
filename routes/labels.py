import json
import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, get_flash, clear_flash, set_flash
from models.audit_log import AuditLog
from models.label import Label
from models.project import Project
from models.ticket import ticket_labels
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


async def _get_project_or_redirect(
    project_id: str,
    db: AsyncSession,
) -> Project | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def _check_label_permission(current_user: User) -> bool:
    return current_user.role in [
        "super_admin",
        "admin",
        "project_manager",
        "team_lead",
    ]


async def _log_audit(
    db: AsyncSession,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
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


@router.get("/projects/{project_id}/labels")
async def list_labels(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    project = await _get_project_or_redirect(project_id, db)
    if project is None:
        return RedirectResponse(url="/projects", status_code=302)

    result = await db.execute(
        select(Label).where(Label.project_id == project_id).order_by(Label.name)
    )
    labels = list(result.scalars().all())

    labels_with_counts = []
    for label in labels:
        count_result = await db.execute(
            select(func.count()).select_from(ticket_labels).where(
                ticket_labels.c.label_id == label.id
            )
        )
        ticket_count = count_result.scalar() or 0
        label.ticket_count = ticket_count
        labels_with_counts.append(label)

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "labels/list.html",
        context={
            "project": project,
            "labels": labels_with_counts,
            "current_user": current_user,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@router.post("/projects/{project_id}/labels")
async def create_label(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
    color: str = Form("#3b82f6"),
):
    if not await _check_label_permission(current_user):
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels", status_code=302
        )
        set_flash(response, "You do not have permission to create labels.", "error")
        return response

    project = await _get_project_or_redirect(project_id, db)
    if project is None:
        return RedirectResponse(url="/projects", status_code=302)

    name = name.strip()
    if not name:
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels", status_code=302
        )
        set_flash(response, "Label name is required.", "error")
        return response

    existing_result = await db.execute(
        select(Label).where(
            Label.project_id == project_id,
            Label.name == name,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels", status_code=302
        )
        set_flash(
            response,
            f"A label named '{name}' already exists in this project.",
            "error",
        )
        return response

    if not color or not color.startswith("#") or len(color) not in (4, 7):
        color = "#3b82f6"

    label = Label(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=name,
        color=color,
        created_at=datetime.utcnow(),
    )
    db.add(label)
    await db.flush()

    await _log_audit(
        db=db,
        actor_id=current_user.id,
        action="create",
        entity_type="label",
        entity_id=label.id,
        changes=json.dumps({"name": name, "color": color, "project_id": project_id}),
    )

    logger.info(
        "User '%s' created label '%s' (id=%s) in project '%s'.",
        current_user.username,
        name,
        label.id,
        project_id,
    )

    response = RedirectResponse(
        url=f"/projects/{project_id}/labels", status_code=302
    )
    set_flash(response, f"Label '{name}' created successfully.", "success")
    return response


@router.post("/projects/{project_id}/labels/{label_id}/edit")
async def edit_label(
    request: Request,
    project_id: str,
    label_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
    color: str = Form("#3b82f6"),
):
    if not await _check_label_permission(current_user):
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels", status_code=302
        )
        set_flash(response, "You do not have permission to edit labels.", "error")
        return response

    project = await _get_project_or_redirect(project_id, db)
    if project is None:
        return RedirectResponse(url="/projects", status_code=302)

    result = await db.execute(
        select(Label).where(Label.id == label_id, Label.project_id == project_id)
    )
    label = result.scalar_one_or_none()
    if label is None:
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels", status_code=302
        )
        set_flash(response, "Label not found.", "error")
        return response

    name = name.strip()
    if not name:
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels", status_code=302
        )
        set_flash(response, "Label name is required.", "error")
        return response

    existing_result = await db.execute(
        select(Label).where(
            Label.project_id == project_id,
            Label.name == name,
            Label.id != label_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels", status_code=302
        )
        set_flash(
            response,
            f"A label named '{name}' already exists in this project.",
            "error",
        )
        return response

    if not color or not color.startswith("#") or len(color) not in (4, 7):
        color = "#3b82f6"

    old_name = label.name
    old_color = label.color

    label.name = name
    label.color = color

    changes = {}
    if old_name != name:
        changes["name"] = {"old": old_name, "new": name}
    if old_color != color:
        changes["color"] = {"old": old_color, "new": color}

    if changes:
        await _log_audit(
            db=db,
            actor_id=current_user.id,
            action="update",
            entity_type="label",
            entity_id=label.id,
            changes=json.dumps(changes),
        )

    logger.info(
        "User '%s' updated label '%s' (id=%s) in project '%s'.",
        current_user.username,
        name,
        label.id,
        project_id,
    )

    response = RedirectResponse(
        url=f"/projects/{project_id}/labels", status_code=302
    )
    set_flash(response, f"Label '{name}' updated successfully.", "success")
    return response


@router.post("/projects/{project_id}/labels/{label_id}/delete")
async def delete_label(
    request: Request,
    project_id: str,
    label_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if not await _check_label_permission(current_user):
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels", status_code=302
        )
        set_flash(response, "You do not have permission to delete labels.", "error")
        return response

    project = await _get_project_or_redirect(project_id, db)
    if project is None:
        return RedirectResponse(url="/projects", status_code=302)

    result = await db.execute(
        select(Label).where(Label.id == label_id, Label.project_id == project_id)
    )
    label = result.scalar_one_or_none()
    if label is None:
        response = RedirectResponse(
            url=f"/projects/{project_id}/labels", status_code=302
        )
        set_flash(response, "Label not found.", "error")
        return response

    label_name = label.name

    await db.execute(
        ticket_labels.delete().where(ticket_labels.c.label_id == label_id)
    )

    await _log_audit(
        db=db,
        actor_id=current_user.id,
        action="delete",
        entity_type="label",
        entity_id=label.id,
        changes=json.dumps({"name": label_name, "project_id": project_id}),
    )

    await db.delete(label)

    logger.info(
        "User '%s' deleted label '%s' (id=%s) from project '%s'.",
        current_user.username,
        label_name,
        label_id,
        project_id,
    )

    response = RedirectResponse(
        url=f"/projects/{project_id}/labels", status_code=302
    )
    set_flash(response, f"Label '{label_name}' deleted successfully.", "success")
    return response