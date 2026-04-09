import logging
from datetime import datetime
from math import ceil
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, get_flash, clear_flash
from models.audit_log import AuditLog
from models.user import User
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

PAGE_SIZE = 20


@router.get("/audit-log")
async def audit_log_list(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
) -> Response:
    if current_user.role not in ["super_admin", "admin"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    query = select(AuditLog)
    count_query = select(func.count()).select_from(AuditLog)

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)

    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
        count_query = count_query.where(AuditLog.entity_type == entity_type)

    if actor:
        from sqlalchemy.orm import selectinload
        query = query.join(AuditLog.actor).where(User.username.ilike(f"%{actor}%"))
        count_query = count_query.join(User, AuditLog.actor_id == User.id).where(
            User.username.ilike(f"%{actor}%")
        )

    if date_from:
        try:
            parsed_from = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.where(AuditLog.timestamp >= parsed_from)
            count_query = count_query.where(AuditLog.timestamp >= parsed_from)
        except ValueError:
            logger.warning("Invalid date_from value: %s", date_from)

    if date_to:
        try:
            parsed_to = datetime.strptime(date_to, "%Y-%m-%d")
            parsed_to = parsed_to.replace(hour=23, minute=59, second=59)
            query = query.where(AuditLog.timestamp <= parsed_to)
            count_query = count_query.where(AuditLog.timestamp <= parsed_to)
        except ValueError:
            logger.warning("Invalid date_to value: %s", date_to)

    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar() or 0
    total_pages = max(1, ceil(total_count / PAGE_SIZE))

    if page > total_pages:
        page = total_pages

    offset = (page - 1) * PAGE_SIZE

    query = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(PAGE_SIZE)

    result = await db.execute(query)
    audit_logs = result.scalars().all()

    filters = {
        "action": action or "",
        "entity_type": entity_type or "",
        "actor": actor or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
    }

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "audit/list.html",
        context={
            "current_user": current_user,
            "audit_logs": audit_logs,
            "filters": filters,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response