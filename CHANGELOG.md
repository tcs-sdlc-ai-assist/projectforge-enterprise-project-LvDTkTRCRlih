# Changelog

All notable changes to ProjectForge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-01-01

### Added

#### Authentication & Authorization
- User registration with email validation and secure password hashing using bcrypt
- User login with JWT-based authentication (access and refresh tokens)
- Session management with token refresh and logout functionality
- Role-Based Access Control (RBAC) with four roles: super_admin, project_manager, team_lead, developer
- Route-level permission enforcement via FastAPI dependency injection
- Password reset functionality with secure token generation

#### Department Management
- Full CRUD operations for departments
- Department listing with pagination and search
- Assign and remove users from departments
- Department detail view with member roster

#### Project Management
- Full CRUD operations for projects with status tracking (planning, active, on_hold, completed, archived)
- Project assignment to departments
- Project member management with role-based access
- Project detail view with associated sprints and tickets
- Project filtering by status and department

#### Sprint Management
- Full CRUD operations for sprints within projects
- Sprint status lifecycle: planning, active, completed
- Sprint date range tracking with start and end dates
- Sprint backlog view showing all associated tickets
- Sprint velocity and progress indicators

#### Ticket Management
- Full CRUD operations for tickets with rich detail fields
- Ticket types: bug, feature, task, improvement
- Ticket priorities: critical, high, medium, low
- Ticket statuses: backlog, todo, in_progress, in_review, done, cancelled
- Ticket assignment to team members
- Sprint association for tickets
- Story point estimation
- Ticket filtering by status, priority, type, assignee, and sprint
- Ticket detail view with full history

#### Kanban Board
- Interactive Kanban board view for sprint tickets
- Drag-and-drop ticket status transitions
- Visual ticket cards displaying key information (title, priority, assignee, story points)
- Column-based layout organized by ticket status
- Real-time board updates on status changes

#### Analytics Dashboard
- Project-level analytics with ticket distribution charts
- Sprint burndown and velocity metrics
- Ticket status breakdown with visual indicators
- Team workload distribution overview
- Department-level project and member statistics
- Filterable date ranges for analytics data

#### Audit Logging
- Comprehensive audit trail for all create, update, and delete operations
- User action tracking with timestamps
- Entity-level change history (projects, tickets, sprints, departments)
- Audit log viewing with filtering by entity type, user, and date range

#### Responsive UI
- Server-side rendered templates using Jinja2
- Tailwind CSS utility-first styling throughout the application
- Responsive layout adapting to desktop, tablet, and mobile viewports
- Sidebar navigation with collapsible menu
- Consistent design system with reusable template components
- Flash message notifications for user feedback
- Form validation with inline error display

#### Database & Seeding
- Async SQLAlchemy 2.0 with aiosqlite for database operations
- Alembic-compatible model definitions with proper relationship mapping
- Database seeding script to populate initial data for development and testing
- Seed data includes: default admin user, sample departments, projects, sprints, and tickets
- Proper foreign key constraints and cascading deletes

#### Developer Experience
- Pydantic v2 schemas for all request and response validation
- Structured logging with Python logging module
- Environment-based configuration via pydantic-settings with .env file support
- CORS middleware configuration for API access
- Comprehensive test suite using pytest with httpx async client
- Modular project structure with clear separation of concerns (routes, models, schemas, services)