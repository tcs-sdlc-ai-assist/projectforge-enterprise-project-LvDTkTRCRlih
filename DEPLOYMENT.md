# Deployment Guide — ProjectForge

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Environment Variable Configuration](#environment-variable-configuration)
4. [Vercel Serverless Deployment](#vercel-serverless-deployment)
5. [vercel.json Explained](#verceljson-explained)
6. [SQLite Considerations for Serverless](#sqlite-considerations-for-serverless)
7. [Static File Serving](#static-file-serving)
8. [Local Development](#local-development)
9. [Troubleshooting Common Issues](#troubleshooting-common-issues)

---

## Overview

ProjectForge is a Python 3.11+ FastAPI application designed for deployment on Vercel's serverless platform. The application uses SQLite for data persistence and Jinja2 for server-side rendering with Tailwind CSS styling.

**Architecture Summary:**
- **Runtime:** Python 3.11+ on Vercel Serverless Functions
- **Framework:** FastAPI with Uvicorn (local) / Mangum or Vercel adapter (serverless)
- **Database:** SQLite via aiosqlite + SQLAlchemy 2.0 async
- **Templates:** Jinja2 with Tailwind CSS
- **Static Assets:** Served via Vercel's CDN or FastAPI's StaticFiles mount

---

## Prerequisites

- Python 3.11 or higher
- A [Vercel](https://vercel.com) account
- [Vercel CLI](https://vercel.com/docs/cli) installed (`npm i -g vercel`)
- Git repository connected to Vercel (recommended)
- All dependencies listed in `requirements.txt`

---

## Environment Variable Configuration

All configuration is managed through environment variables. In production, set these in the Vercel dashboard under **Settings → Environment Variables**.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | — | Secret key for JWT signing and session security. Must be a long random string (min 32 chars). Generate with: `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./projectforge.db` | SQLAlchemy async database URL. For serverless, use `/tmp/projectforge.db` path. |
| `ENVIRONMENT` | No | `production` | Deployment environment: `development`, `staging`, or `production`. |
| `DEBUG` | No | `false` | Enable debug mode. **Never set to `true` in production.** |
| `ALLOWED_ORIGINS` | No | `*` | Comma-separated list of allowed CORS origins. Set explicitly in production. |
| `LOG_LEVEL` | No | `info` | Logging level: `debug`, `info`, `warning`, `error`, `critical`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | JWT access token expiration time in minutes. |

### Setting Environment Variables on Vercel

**Via Vercel Dashboard:**
1. Navigate to your project on [vercel.com](https://vercel.com)
2. Go to **Settings** → **Environment Variables**
3. Add each variable with the appropriate scope (Production, Preview, Development)
4. Redeploy for changes to take effect

**Via Vercel CLI:**
```bash
vercel env add SECRET_KEY production
vercel env add DATABASE_URL production
vercel env add ALLOWED_ORIGINS production
```

**Local `.env` file (for development only — never commit this):**
```env
SECRET_KEY=your-local-dev-secret-key-change-in-production
DATABASE_URL=sqlite+aiosqlite:///./projectforge.db
ENVIRONMENT=development
DEBUG=true
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
LOG_LEVEL=debug
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

---

## Vercel Serverless Deployment

### Step 1: Prepare the Project

Ensure your project structure includes:
```
projectforge/
├── main.py              # FastAPI application entry point
├── requirements.txt     # Python dependencies
├── vercel.json          # Vercel deployment configuration
├── .env                 # Local env vars (git-ignored)
├── .gitignore
├── models/
├── routes/
├── schemas/
├── services/
├── dependencies/
├── templates/
└── static/
```

### Step 2: Install Vercel CLI

```bash
npm install -g vercel
```

### Step 3: Link Your Project

```bash
cd projectforge
vercel link
```

Follow the prompts to connect to your Vercel account and project.

### Step 4: Configure Environment Variables

```bash
vercel env add SECRET_KEY production
# Enter your secret key when prompted
```

Repeat for all required environment variables.

### Step 5: Deploy

**Preview deployment (from any branch):**
```bash
vercel
```

**Production deployment:**
```bash
vercel --prod
```

**Automatic deployments via Git:**
Once your repository is connected to Vercel, every push to `main` triggers a production deployment, and every push to other branches triggers a preview deployment.

### Step 6: Verify

After deployment, visit your Vercel URL and check:
- The home page loads correctly
- Authentication endpoints respond
- Static assets (CSS, JS, images) load properly
- Database operations work (create, read, update)

---

## vercel.json Explained

```json
{
  "version": 2,
  "builds": [
    {
      "src": "main.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/static/(.*)",
      "dest": "/static/$1"
    },
    {
      "src": "/(.*)",
      "dest": "main.py"
    }
  ]
}
```

### Configuration Breakdown

| Key | Purpose |
|---|---|
| `version` | Vercel platform version. Always use `2`. |
| `builds` | Defines how to build the application. `@vercel/python` installs dependencies from `requirements.txt` and creates a serverless function from `main.py`. |
| `builds[].src` | Entry point file. Must export a FastAPI/ASGI `app` object. |
| `builds[].use` | Builder to use. `@vercel/python` handles Python serverless functions. |
| `routes` | URL routing rules processed in order. |
| `routes[0]` | Static file route — serves files from the `static/` directory directly via Vercel's CDN, bypassing the Python function for better performance. |
| `routes[1]` | Catch-all route — sends all other requests to the FastAPI application in `main.py`. |

### Important Notes on vercel.json

- **Route order matters.** More specific routes must come before the catch-all. Static files are matched first so they don't hit the serverless function.
- **The `@vercel/python` builder** automatically reads `requirements.txt` from the project root. No `pip install` step is needed.
- **The entry point (`main.py`)** must expose the ASGI app as a module-level variable named `app`. Vercel's Python runtime expects this convention.
- **Maximum function size** is 250 MB (compressed). Monitor your dependency size — large packages like `torch` or `tensorflow` will exceed this limit.
- **Execution timeout** is 10 seconds on the Hobby plan and 60 seconds on Pro. Optimize slow database queries accordingly.

---

## SQLite Considerations for Serverless

SQLite on serverless platforms has significant limitations that you must understand and plan for.

### The Core Problem

Vercel serverless functions are **ephemeral** — each invocation may run on a different container. The local filesystem is:
- **Read-only** except for the `/tmp` directory
- **Not shared** between function invocations
- **Not persistent** — `/tmp` contents are lost when the container is recycled

This means a standard SQLite database file **will not persist** between requests on separate containers.

### Recommended Approaches

#### Option 1: `/tmp` Directory (Development / Demo Only)

Configure the database URL to use `/tmp`:

```python
# In your settings/config
DATABASE_URL = "sqlite+aiosqlite:////tmp/projectforge.db"
```

**Pros:** Simple, works immediately.
**Cons:** Data is lost when the container recycles (typically after minutes of inactivity). Not suitable for production.

#### Option 2: Turso / libSQL (Recommended for Production)

[Turso](https://turso.tech) provides SQLite-compatible databases with an HTTP-based protocol that works in serverless environments.

1. Create a Turso database:
   ```bash
   turso db create projectforge
   turso db tokens create projectforge
   ```

2. Set environment variables:
   ```
   DATABASE_URL=libsql://your-db-name-your-org.turso.io
   DATABASE_AUTH_TOKEN=your-auth-token
   ```

3. Use the `libsql-experimental` Python package instead of `aiosqlite`.

#### Option 3: External PostgreSQL / MySQL

For production workloads, migrate to a hosted relational database:
- **Vercel Postgres** (powered by Neon)
- **PlanetScale** (MySQL-compatible)
- **Supabase** (PostgreSQL)
- **Railway** (PostgreSQL)

Update `DATABASE_URL` to the provider's connection string and swap `aiosqlite` for `asyncpg` (PostgreSQL) or `aiomysql` (MySQL) in `requirements.txt`.

#### Option 4: SQLite with Litestream (Self-Hosted)

If deploying to a VPS or container platform (not Vercel), use [Litestream](https://litestream.io) to replicate SQLite to S3-compatible storage for durability.

### SQLite Serverless Best Practices

1. **Always use WAL mode** for better concurrent read performance:
   ```python
   @event.listens_for(engine.sync_engine, "connect")
   def set_sqlite_pragma(dbapi_connection, connection_record):
       cursor = dbapi_connection.cursor()
       cursor.execute("PRAGMA journal_mode=WAL")
       cursor.execute("PRAGMA busy_timeout=5000")
       cursor.close()
   ```

2. **Initialize the database on cold start.** Since `/tmp` may be empty, run `Base.metadata.create_all()` at application startup to ensure tables exist.

3. **Keep transactions short.** SQLite allows only one writer at a time. Long-running write transactions will cause `database is locked` errors under concurrent load.

4. **Do not rely on SQLite for session storage** in serverless. Use signed cookies (JWT) or an external session store (Redis) instead.

---

## Static File Serving

### Directory Structure

```
static/
├── css/
│   └── styles.css       # Compiled Tailwind CSS
├── js/
│   └── app.js           # Client-side JavaScript
├── images/
│   └── logo.png
└── favicon.ico
```

### FastAPI Static Mount

In `main.py`, static files are mounted for local development:

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
```

### Vercel Static Serving

On Vercel, the `routes` configuration in `vercel.json` serves static files directly from the CDN:

```json
{
  "src": "/static/(.*)",
  "dest": "/static/$1"
}
```

This means static files are served without invoking the Python serverless function, resulting in:
- **Faster response times** (CDN edge delivery)
- **Lower costs** (no function invocation)
- **Reduced cold starts** for static assets

### Tailwind CSS Build

If you modify Tailwind styles, rebuild the CSS before deploying:

```bash
npx tailwindcss -i ./static/css/input.css -o ./static/css/styles.css --minify
```

Or add a build script to `package.json`:
```json
{
  "scripts": {
    "build:css": "tailwindcss -i ./static/css/input.css -o ./static/css/styles.css --minify",
    "watch:css": "tailwindcss -i ./static/css/input.css -o ./static/css/styles.css --watch"
  }
}
```

### Cache Headers

For production, configure cache headers for static assets in `vercel.json`:

```json
{
  "headers": [
    {
      "source": "/static/(.*)",
      "headers": [
        {
          "key": "Cache-Control",
          "value": "public, max-age=31536000, immutable"
        }
      ]
    }
  ]
}
```

Use content hashing or versioned filenames (e.g., `styles.abc123.css`) to enable aggressive caching while ensuring updates are picked up.

---

## Local Development

### Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd projectforge

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env with your local settings

# Run the application
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_auth.py

# Run with coverage
pytest --cov=. --cov-report=html
```

### Vercel Dev (Local Serverless Simulation)

```bash
vercel dev
```

This simulates the Vercel serverless environment locally, including the routing rules from `vercel.json`.

---

## Troubleshooting Common Issues

### 1. `ModuleNotFoundError: No module named 'xyz'`

**Cause:** A dependency is missing from `requirements.txt`.

**Fix:** Ensure all imports have corresponding entries in `requirements.txt`:
```bash
pip freeze > requirements.txt
# Or manually add the missing package
```

Common missing packages:
- `python-multipart` — required for `Form()` data parsing in FastAPI
- `pydantic-settings` — required for `BaseSettings` in Pydantic v2
- `python-dotenv` — required by pydantic-settings for `.env` file loading
- `aiosqlite` — required for async SQLite with SQLAlchemy
- `python-jose[cryptography]` — required for JWT token handling
- `bcrypt==4.0.1` — required for password hashing (pin this exact version if using passlib)

### 2. `Internal Server Error` (500) on Vercel with No Logs

**Cause:** The serverless function crashed during cold start, often due to import errors or missing environment variables.

**Fix:**
1. Check Vercel Function Logs: **Project → Deployments → Functions tab → View Logs**
2. Verify all required environment variables are set in Vercel dashboard
3. Test locally with `vercel dev` to reproduce the error
4. Ensure `main.py` exports `app` at the module level (not inside `if __name__ == "__main__"`)

### 3. `database is locked` Errors

**Cause:** Multiple concurrent writes to SQLite. SQLite only supports one writer at a time.

**Fix:**
- Enable WAL mode: `PRAGMA journal_mode=WAL`
- Set busy timeout: `PRAGMA busy_timeout=5000`
- Keep write transactions as short as possible
- For high-concurrency production use, migrate to PostgreSQL

### 4. Database Resets Between Requests on Vercel

**Cause:** SQLite file in `/tmp` is lost when the serverless container recycles.

**Fix:** This is expected behavior for ephemeral serverless. See [SQLite Considerations](#sqlite-considerations-for-serverless) for persistent alternatives (Turso, external PostgreSQL).

### 5. Static Files Return 404

**Cause:** Incorrect path configuration or missing files in the deployment.

**Fix:**
1. Verify `static/` directory is not in `.gitignore` (or `.vercelignore`)
2. Check `vercel.json` routes include the static file pattern
3. Ensure the `StaticFiles` mount in `main.py` uses an absolute path:
   ```python
   BASE_DIR = Path(__file__).resolve().parent
   app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
   ```

### 6. `MissingGreenlet: greenlet_spawn has not been called`

**Cause:** Lazy loading a SQLAlchemy relationship inside an async context (e.g., accessing `user.projects` in a Jinja2 template without eager loading).

**Fix:** Add `lazy="selectin"` to ALL `relationship()` declarations, or use `selectinload()` in queries:
```python
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(User).where(User.id == user_id).options(selectinload(User.projects))
)
```

### 7. `TypeError: unhashable type: 'dict'` in TemplateResponse

**Cause:** Using the old Starlette `TemplateResponse` API.

**Fix:** Use the new API (Starlette 1.0+ / FastAPI 0.135+):
```python
# WRONG
return templates.TemplateResponse("page.html", {"request": request, "data": data})

# CORRECT
return templates.TemplateResponse(request, "page.html", context={"data": data})
```

### 8. CORS Errors in Browser Console

**Cause:** Frontend origin not included in `ALLOWED_ORIGINS`.

**Fix:** Add the frontend URL to the `ALLOWED_ORIGINS` environment variable:
```
ALLOWED_ORIGINS=https://your-frontend.vercel.app,https://your-domain.com
```

### 9. Cold Start Latency (Slow First Request)

**Cause:** Vercel serverless functions have a cold start penalty when a new container is provisioned.

**Fix:**
- Minimize dependency count and size in `requirements.txt`
- Remove unused packages
- Use lightweight alternatives where possible (e.g., `orjson` instead of default JSON)
- On Vercel Pro, enable **Fluid Compute** or **Cron Jobs** to keep functions warm

### 10. `Function has crashed` or `FUNCTION_INVOCATION_TIMEOUT`

**Cause:** The function exceeded the execution time limit (10s Hobby / 60s Pro) or ran out of memory (1024 MB default).

**Fix:**
- Optimize slow database queries (add indexes, reduce N+1 queries)
- Paginate large result sets
- Move heavy processing to background tasks or a separate worker
- Increase memory/timeout in `vercel.json`:
  ```json
  {
    "functions": {
      "main.py": {
        "memory": 1024,
        "maxDuration": 30
      }
    }
  }
  ```

### 11. `ImportError: cannot import name 'X' from 'Y'`

**Cause:** Typo in import name, wrong package version, or circular import.

**Fix:**
1. Verify the exact symbol name in the package documentation
2. Check package version in `requirements.txt` matches the API you're using (e.g., Pydantic v1 vs v2)
3. Check for circular imports: models should never import from routes or services

### 12. `.env` File Not Loading on Vercel

**Cause:** `.env` files are for local development only. Vercel does not read `.env` files.

**Fix:** Set all environment variables through the Vercel dashboard or CLI:
```bash
vercel env add VARIABLE_NAME production
```

---

## Deployment Checklist

Before deploying to production, verify:

- [ ] `SECRET_KEY` is set to a unique, random value (not the development default)
- [ ] `DEBUG` is `false`
- [ ] `ALLOWED_ORIGINS` is set to specific domains (not `*`)
- [ ] All dependencies in `requirements.txt` have pinned versions
- [ ] `bcrypt==4.0.1` is pinned if using passlib
- [ ] Database migration/initialization runs on startup
- [ ] Static assets are built and committed (Tailwind CSS compiled)
- [ ] `.env` file is in `.gitignore`
- [ ] No `print()` statements in production code (use `logging` module)
- [ ] All sensitive data is in environment variables, not hardcoded
- [ ] Error handling returns appropriate HTTP status codes
- [ ] CORS is configured for the production frontend domain
- [ ] SQLite persistence strategy is chosen and configured