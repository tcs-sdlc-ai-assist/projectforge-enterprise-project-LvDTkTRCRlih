import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Sprint(Base):
    __tablename__ = "sprints"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("planning", "active", "completed", name="sprint_status"),
        nullable=False,
        default="planning",
        server_default="planning",
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    project: Mapped["Project"] = relationship(  # noqa: F821
        "Project",
        back_populates="sprints",
        lazy="selectin",
    )
    tickets: Mapped[list["Ticket"]] = relationship(  # noqa: F821
        "Ticket",
        back_populates="sprint",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Sprint(id={self.id!r}, name={self.name!r}, status={self.status!r})>"