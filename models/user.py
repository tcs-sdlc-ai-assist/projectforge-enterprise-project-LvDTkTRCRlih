import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    username: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
    )
    first_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )
    last_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="developer",
    )
    department_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    department = relationship(
        "Department",
        back_populates="members",
        lazy="selectin",
    )
    owned_projects = relationship(
        "Project",
        back_populates="owner",
        lazy="selectin",
        foreign_keys="[Project.owner_id]",
    )
    assigned_tickets = relationship(
        "Ticket",
        back_populates="assignee",
        lazy="selectin",
        foreign_keys="[Ticket.assignee_id]",
    )
    reported_tickets = relationship(
        "Ticket",
        back_populates="reporter",
        lazy="selectin",
        foreign_keys="[Ticket.reporter_id]",
    )
    comments = relationship(
        "Comment",
        back_populates="user",
        lazy="selectin",
    )
    time_entries = relationship(
        "TimeEntry",
        back_populates="user",
        lazy="selectin",
    )
    audit_logs = relationship(
        "AuditLog",
        back_populates="actor",
        lazy="selectin",
    )
    activities = relationship(
        "Activity",
        back_populates="user",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id!r}, username={self.username!r}, role={self.role!r})>"