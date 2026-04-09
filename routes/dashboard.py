import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, get_flash, clear_flash
from models.activity import Activity
from models.audit_log import AuditLog
from models.project import Project
from models.sprint import Sprint
from models.ticket import Ticket
from models.time_entry import TimeEntry
from models.user import User
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


@router.get("/dashboard")
async def dashboard_page(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    flash_messages = get_flash(request)

    total_projects = await db.scalar(
        select(func.count()).select_from(Project)
    ) or 0

    active_sprints = await db.scalar(
        select(func.count()).select_from(Sprint).where(Sprint.status == "active")
    ) or 0

    open_statuses = ["backlog", "todo", "in_progress", "in_review"]
    open_tickets = await db.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.status.in_(open_statuses))
    ) or 0

    overdue_tickets = 0
    overdue_result = await db.execute(
        select(func.count()).select_from(Ticket).where(
            Ticket.status.in_(open_statuses),
            Ticket.sprint_id.isnot(None),
        )
    )
    sprint_based_overdue = overdue_result.scalar() or 0

    from datetime import date as date_type
    overdue_sprint_result = await db.execute(
        select(Sprint.id).where(
            Sprint.status == "active",
            Sprint.end_date < date_type.today(),
        )
    )
    overdue_sprint_ids = [row[0] for row in overdue_sprint_result.fetchall()]

    if overdue_sprint_ids:
        overdue_tickets = await db.scalar(
            select(func.count()).select_from(Ticket).where(
                Ticket.sprint_id.in_(overdue_sprint_ids),
                Ticket.status.in_(open_statuses),
            )
        ) or 0

    total_hours_result = await db.scalar(
        select(func.coalesce(func.sum(TimeEntry.hours), 0.0)).select_from(TimeEntry)
    )
    total_hours_logged = round(float(total_hours_result or 0.0), 1)

    all_statuses = ["backlog", "todo", "in_progress", "in_review", "done", "closed", "cancelled"]
    ticket_status_distribution = []
    for status in all_statuses:
        count = await db.scalar(
            select(func.count()).select_from(Ticket).where(Ticket.status == status)
        ) or 0
        if count > 0:
            ticket_status_distribution.append({"status": status, "count": count})

    recent_activities = []
    try:
        audit_result = await db.execute(
            select(AuditLog)
            .order_by(AuditLog.timestamp.desc())
            .limit(10)
        )
        audit_logs = audit_result.scalars().all()

        for log_entry in audit_logs:
            action_map = {
                "create": "created",
                "update": "updated",
                "delete": "deleted",
            }
            action_display = action_map.get(log_entry.action, log_entry.action)

            username = "System"
            if log_entry.actor:
                username = log_entry.actor.username

            entity_name = ""
            if log_entry.changes:
                import json
                try:
                    changes_data = json.loads(log_entry.changes)
                    if isinstance(changes_data, dict):
                        entity_name = changes_data.get("name", "")
                except (json.JSONDecodeError, TypeError):
                    pass

            timestamp_str = ""
            if log_entry.timestamp:
                timestamp_str = log_entry.timestamp.strftime("%b %d, %Y %I:%M %p")

            recent_activities.append({
                "username": username,
                "action": action_display,
                "entity_type": log_entry.entity_type or "",
                "entity_name": entity_name,
                "timestamp": timestamp_str,
            })
    except Exception:
        logger.exception("Failed to fetch recent activities for dashboard.")

    projects_data = []
    try:
        projects_result = await db.execute(
            select(Project).order_by(Project.updated_at.desc()).limit(20)
        )
        projects = projects_result.scalars().all()

        for project in projects:
            project_open = await db.scalar(
                select(func.count()).select_from(Ticket).where(
                    Ticket.project_id == project.id,
                    Ticket.status.in_(open_statuses),
                )
            ) or 0

            project_done = await db.scalar(
                select(func.count()).select_from(Ticket).where(
                    Ticket.project_id == project.id,
                    Ticket.status.in_(["done", "closed"]),
                )
            ) or 0

            project_overdue = 0
            if overdue_sprint_ids:
                project_overdue = await db.scalar(
                    select(func.count()).select_from(Ticket).where(
                        Ticket.project_id == project.id,
                        Ticket.sprint_id.in_(overdue_sprint_ids),
                        Ticket.status.in_(open_statuses),
                    )
                ) or 0

            department_name = ""
            if project.department:
                department_name = project.department.name

            projects_data.append({
                "id": project.id,
                "name": project.name,
                "status": project.status,
                "department_name": department_name,
                "open_tickets": project_open,
                "done_tickets": project_done,
                "overdue_tickets": project_overdue,
            })
    except Exception:
        logger.exception("Failed to fetch project health data for dashboard.")

    stats = {
        "total_projects": total_projects,
        "active_sprints": active_sprints,
        "open_tickets": open_tickets,
        "overdue_tickets": overdue_tickets,
        "total_hours_logged": total_hours_logged,
    }

    response = templates.TemplateResponse(
        request,
        "dashboard/index.html",
        context={
            "current_user": current_user,
            "stats": stats,
            "ticket_status_distribution": ticket_status_distribution,
            "recent_activities": recent_activities,
            "projects": projects_data,
            "flash_messages": flash_messages,
        },
    )

    if flash_messages:
        clear_flash(response)

    return response