import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from database import close_db, init_db
from dependencies import get_current_user_optional, get_flash, clear_flash
from routes import (
    audit_router,
    auth_router,
    dashboard_router,
    departments_router,
    labels_router,
    projects_router,
    sprints_router,
    tickets_router,
    users_router,
)
from seed import seed_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("Starting ProjectForge application...")
    logger.info("Database URL: %s", settings.DATABASE_URL)

    await init_db()
    logger.info("Database tables initialized.")

    await seed_database()
    logger.info("Database seeding complete.")

    _log_registered_routes(application)

    yield

    await close_db()
    logger.info("Application shutdown complete.")


def _log_registered_routes(application: FastAPI) -> None:
    route_count = 0
    for route in application.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods = ", ".join(sorted(route.methods))
            logger.info("Route registered: [%s] %s", methods, route.path)
            route_count += 1
    logger.info("Total routes registered: %d", route_count)


app = FastAPI(
    title="ProjectForge",
    description="A comprehensive project management platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(departments_router)
app.include_router(projects_router)
app.include_router(sprints_router)
app.include_router(tickets_router)
app.include_router(labels_router)
app.include_router(users_router)
app.include_router(audit_router)


@app.get("/")
async def root(request: Request):
    from database import async_session_factory
    from models.user import User
    from sqlalchemy import select

    async with async_session_factory() as session:
        try:
            from dependencies import get_session_data

            session_data = get_session_data(request)
            if session_data:
                user_id = session_data.get("user_id")
                if user_id:
                    result = await session.execute(
                        select(User).where(User.id == user_id)
                    )
                    user = result.scalar_one_or_none()
                    if user and user.is_active:
                        return RedirectResponse(url="/dashboard", status_code=302)
        except Exception:
            pass

    flash_messages = get_flash(request)
    response = templates.TemplateResponse(
        request,
        "landing.html",
        context={
            "current_user": None,
            "flash_messages": flash_messages,
        },
    )
    clear_flash(response)
    return response


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    current_user = None
    try:
        from database import async_session_factory
        from models.user import User
        from sqlalchemy import select
        from dependencies import get_session_data

        session_data = get_session_data(request)
        if session_data:
            user_id = session_data.get("user_id")
            if user_id:
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(User).where(User.id == user_id)
                    )
                    user = result.scalar_one_or_none()
                    if user and user.is_active:
                        current_user = user
    except Exception:
        pass

    return templates.TemplateResponse(
        request,
        "errors/404.html",
        context={
            "current_user": current_user,
            "flash_messages": [],
        },
        status_code=404,
    )


logger.info("ProjectForge application configured successfully.")
logger.info("Models loaded: User, Department, Project, Sprint, Ticket, Label, Comment, TimeEntry, AuditLog")