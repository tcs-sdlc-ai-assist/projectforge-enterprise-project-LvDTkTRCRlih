import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session_factory
from models.department import Department
from models.user import User

logger = logging.getLogger(__name__)


async def seed_default_department(session: AsyncSession) -> Department:
    """Create the default 'Engineering' department if it doesn't exist."""
    result = await session.execute(
        select(Department).where(Department.name == "Engineering")
    )
    department = result.scalars().first()

    if department is None:
        department = Department(
            id=str(uuid.uuid4()),
            name="Engineering",
            description="Software engineering and development team",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(department)
        await session.flush()
        logger.info("Created default 'Engineering' department (id=%s).", department.id)
    else:
        logger.info("Default 'Engineering' department already exists (id=%s).", department.id)

    return department


async def seed_default_admin(session: AsyncSession, department: Department) -> None:
    """Create the default admin user from env vars if it doesn't exist."""
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    username = settings.DEFAULT_ADMIN_USERNAME
    result = await session.execute(
        select(User).where(User.username == username)
    )
    admin = result.scalars().first()

    if admin is None:
        hashed_password = pwd_context.hash(settings.DEFAULT_ADMIN_PASSWORD)
        admin = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=hashed_password,
            email=f"{username}@projectforge.io",
            first_name="Admin",
            last_name="User",
            role="super_admin",
            department_id=department.id,
            is_active=True,
        )
        session.add(admin)
        await session.flush()
        logger.info("Created default admin user '%s' (id=%s).", username, admin.id)
    else:
        logger.info("Default admin user '%s' already exists (id=%s).", username, admin.id)


async def seed_label_templates(session: AsyncSession) -> None:
    """Log suggested label templates. Labels are project-scoped, so we only log suggestions."""
    suggested_labels = [
        {"name": "bug", "color": "#ef4444"},
        {"name": "enhancement", "color": "#3b82f6"},
        {"name": "documentation", "color": "#8b5cf6"},
        {"name": "good first issue", "color": "#22c55e"},
        {"name": "help wanted", "color": "#f59e0b"},
        {"name": "priority: high", "color": "#dc2626"},
        {"name": "priority: low", "color": "#6b7280"},
        {"name": "wontfix", "color": "#1f2937"},
        {"name": "duplicate", "color": "#9ca3af"},
        {"name": "invalid", "color": "#f97316"},
    ]
    logger.info(
        "Suggested label templates for new projects: %s",
        ", ".join(label["name"] for label in suggested_labels),
    )


async def seed_database() -> None:
    """Run all seed operations inside a single session/transaction."""
    logger.info("Starting database seeding...")

    async with async_session_factory() as session:
        try:
            department = await seed_default_department(session)
            await seed_default_admin(session, department)
            await seed_label_templates(session)
            await session.commit()
            logger.info("Database seeding completed successfully.")
        except Exception:
            await session.rollback()
            logger.exception("Database seeding failed.")
            raise
        finally:
            await session.close()