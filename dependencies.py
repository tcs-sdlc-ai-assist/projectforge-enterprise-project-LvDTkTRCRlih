import json
import logging
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.user import User

logger = logging.getLogger(__name__)

serializer = URLSafeTimedSerializer(settings.SECRET_KEY)

SESSION_COOKIE_NAME = "session"
FLASH_COOKIE_NAME = "flash_messages"


def create_session_cookie(response: Response, user_id: str) -> None:
    token = serializer.dumps({"user_id": user_id})
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.TOKEN_EXPIRY_SECONDS,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    response.delete_cookie(key=FLASH_COOKIE_NAME)


def get_session_data(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    try:
        data = serializer.loads(token, max_age=settings.TOKEN_EXPIRY_SECONDS)
        return data
    except SignatureExpired:
        logger.warning("Session cookie expired.")
        return None
    except BadSignature:
        logger.warning("Invalid session cookie signature.")
        return None


async def get_current_user_optional(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    session_data = get_session_data(request)
    if not session_data:
        return None

    user_id = session_data.get("user_id")
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        return None

    if not user.is_active:
        return None

    return user


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    user = await get_current_user_optional(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_role(allowed_roles: list[str]):
    async def role_dependency(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return role_dependency


async def get_project_member(
    project_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if current_user.role in ["super_admin", "admin"]:
        return current_user

    from models.project import Project, project_members

    result = await db.execute(
        select(project_members).where(
            project_members.c.project_id == project_id,
            project_members.c.user_id == current_user.id,
        )
    )
    membership = result.first()

    if membership is None:
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.owner_id == current_user.id,
            )
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise HTTPException(
                status_code=403,
                detail="You are not a member of this project.",
            )

    return current_user


def set_flash(response: Response, message: str, category: str = "info") -> None:
    flash_data = json.dumps([{"text": message, "category": category}])
    response.set_cookie(
        key=FLASH_COOKIE_NAME,
        value=flash_data,
        httponly=True,
        samesite="lax",
        max_age=60,
    )


def get_flash(request: Request) -> list[dict]:
    flash_cookie = request.cookies.get(FLASH_COOKIE_NAME)
    if not flash_cookie:
        return []
    try:
        messages = json.loads(flash_cookie)
        if isinstance(messages, list):
            return messages
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def clear_flash(response: Response) -> None:
    response.delete_cookie(key=FLASH_COOKIE_NAME)