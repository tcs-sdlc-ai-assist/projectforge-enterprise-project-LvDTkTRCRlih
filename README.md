# ProjectForge

A comprehensive project management platform built with Python and FastAPI, designed for teams to plan, track, and deliver projects efficiently.

## Features

- **User Authentication & Authorization** — Secure login/registration with JWT tokens and role-based access control
- **Project Management** — Create, update, and archive projects with detailed metadata
- **Sprint Planning** — Organize work into time-boxed sprints with start/end dates and goals
- **Ticket Tracking** — Full-featured ticket system with priorities, statuses, assignments, and comments
- **Role-Based Access Control** — Four distinct roles with granular permissions
- **Dashboard** — Overview of active projects, current sprints, and recent activity
- **Search & Filtering** — Find tickets and projects quickly with advanced filters
- **Activity Feed** — Track changes and updates across the platform
- **RAG-Powered Knowledge Base** — Vector search over project documents using ChromaDB

## Tech Stack

- **Backend:** Python 3.11+, FastAPI
- **Database:** SQLite with SQLAlchemy 2.0 (async via aiosqlite)
- **Authentication:** JWT tokens via python-jose, bcrypt password hashing
- **Validation:** Pydantic v2
- **Templates:** Jinja2 with Tailwind CSS
- **Vector Database:** ChromaDB for document similarity search
- **Server:** Uvicorn (ASGI)

## Folder Structure

```
projectforge/
├── main.py                  # FastAPI application entry point
├── config.py                # Pydantic Settings configuration
├── database.py              # SQLAlchemy async engine and session setup
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables (not committed)
├── README.md                # This file
├── models/
│   ├── __init__.py          # Model re-exports
│   ├── user.py              # User model
│   ├── project.py           # Project model
│   ├── sprint.py            # Sprint model
│   ├── ticket.py            # Ticket model
│   ├── comment.py           # Comment model
│   └── activity.py          # Activity log model
├── schemas/
│   ├── __init__.py          # Schema re-exports
│   ├── user.py              # User request/response schemas
│   ├── project.py           # Project schemas
│   ├── sprint.py            # Sprint schemas
│   ├── ticket.py            # Ticket schemas
│   └── comment.py           # Comment schemas
├── routes/
│   ├── __init__.py          # Router aggregation
│   ├── auth.py              # Authentication routes (login, register, logout)
│   ├── dashboard.py         # Dashboard route
│   ├── projects.py          # Project CRUD routes
│   ├── sprints.py           # Sprint CRUD routes
│   ├── tickets.py           # Ticket CRUD routes
│   └── comments.py          # Comment routes
├── services/
│   ├── __init__.py
│   ├── auth.py              # Authentication logic (JWT, password hashing)
│   ├── project.py           # Project business logic
│   ├── sprint.py            # Sprint business logic
│   ├── ticket.py            # Ticket business logic
│   └── vector.py            # ChromaDB vector search service
├── dependencies/
│   ├── __init__.py
│   └── auth.py              # Auth dependency injection (get_current_user)
├── templates/
│   ├── base.html            # Base layout with Tailwind CDN and navigation
│   ├── login.html           # Login page
│   ├── register.html        # Registration page
│   ├── dashboard.html       # Dashboard overview
│   ├── projects/
│   │   ├── list.html        # Project listing
│   │   ├── detail.html      # Project detail view
│   │   └── form.html        # Project create/edit form
│   ├── sprints/
│   │   ├── list.html        # Sprint listing
│   │   ├── detail.html      # Sprint detail view
│   │   └── form.html        # Sprint create/edit form
│   └── tickets/
│       ├── list.html        # Ticket listing
│       ├── detail.html      # Ticket detail with comments
│       └── form.html        # Ticket create/edit form
├── static/
│   └── css/
│       └── custom.css       # Minimal custom styles (if needed)
└── tests/
    ├── __init__.py
    ├── conftest.py           # Shared fixtures (async client, test DB)
    ├── test_auth.py          # Authentication tests
    ├── test_projects.py      # Project endpoint tests
    ├── test_sprints.py       # Sprint endpoint tests
    └── test_tickets.py       # Ticket endpoint tests
```

## Setup Instructions

### 1. Clone the Repository

```bash
git clone <repository-url>
cd projectforge
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
# Application
APP_NAME=ProjectForge
DEBUG=true

# Security
SECRET_KEY=your-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Database
DATABASE_URL=sqlite+aiosqlite:///./projectforge.db

# ChromaDB
CHROMA_DB_PATH=./chroma_data
CHROMA_COLLECTION_NAME=projectforge_docs

# CORS (comma-separated origins)
CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

### 5. Run the Application

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The application will be available at [http://localhost:8000](http://localhost:8000).

### 6. Run Tests

```bash
pytest tests/ -v
```

## Default Admin Credentials

On first startup, a default admin account is created:

| Field    | Value                  |
|----------|------------------------|
| Email    | `admin@projectforge.io`|
| Password | `admin123!`            |

> **⚠️ Important:** Change the default admin password immediately after first login in production environments.

## Roles & Permissions

| Role              | Description                                                                 |
|-------------------|-----------------------------------------------------------------------------|
| `super_admin`     | Full system access. Can manage all users, projects, and settings.           |
| `project_manager` | Can create and manage projects, sprints, and assign tickets.                |
| `developer`       | Can view assigned projects, update ticket statuses, and add comments.       |
| `viewer`          | Read-only access to projects and tickets they are granted access to.        |

## API Documentation

FastAPI provides interactive API documentation out of the box:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Deployment Notes

### Vercel

1. Add a `vercel.json` configuration file:

```json
{
  "builds": [
    {
      "src": "main.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "main.py"
    }
  ]
}
```

2. Set all environment variables from `.env` in the Vercel project dashboard under **Settings → Environment Variables**.

3. For production, update the following:
   - Set `DEBUG=false`
   - Use a strong, unique `SECRET_KEY`
   - Configure `CORS_ORIGINS` to match your production domain
   - Change the default admin password immediately after deployment

4. **Database consideration:** SQLite is not recommended for Vercel serverless deployments. For production, consider switching to PostgreSQL with `asyncpg`:
   ```
   DATABASE_URL=postgresql+asyncpg://user:password@host:5432/projectforge
   ```

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## License

Private — All rights reserved.