from routes.auth import router as auth_router
from routes.dashboard import router as dashboard_router
from routes.departments import router as departments_router
from routes.projects import router as projects_router
from routes.sprints import router as sprints_router
from routes.tickets import router as tickets_router
from routes.labels import router as labels_router
from routes.users import router as users_router
from routes.audit import router as audit_router

__all__ = [
    "auth_router",
    "dashboard_router",
    "departments_router",
    "projects_router",
    "sprints_router",
    "tickets_router",
    "labels_router",
    "users_router",
    "audit_router",
]