import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship

from database import Base


ticket_labels = Table(
    "ticket_labels",
    Base.metadata,
    Column("ticket_id", String(36), ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", String(36), ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
)


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    sprint_id = Column(String(36), ForeignKey("sprints.id", ondelete="SET NULL"), nullable=True)
    assignee_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reporter_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    parent_id = Column(String(36), ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    status = Column(
        Enum(
            "backlog", "todo", "in_progress", "in_review", "done", "closed",
            name="ticket_status",
        ),
        nullable=False,
        default="backlog",
    )
    type = Column(
        Enum(
            "feature", "bug", "task", "improvement",
            name="ticket_type",
        ),
        nullable=False,
        default="task",
    )
    priority = Column(
        Enum(
            "critical", "high", "medium", "low",
            name="ticket_priority",
        ),
        nullable=False,
        default="medium",
    )

    story_points = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    project = relationship("Project", back_populates="tickets", lazy="selectin")
    sprint = relationship("Sprint", back_populates="tickets", lazy="selectin")
    assignee = relationship(
        "User",
        foreign_keys=[assignee_id],
        back_populates="assigned_tickets",
        lazy="selectin",
    )
    reporter = relationship(
        "User",
        foreign_keys=[reporter_id],
        back_populates="reported_tickets",
        lazy="selectin",
    )
    parent = relationship(
        "Ticket",
        remote_side=[id],
        back_populates="children",
        lazy="selectin",
    )
    children = relationship(
        "Ticket",
        back_populates="parent",
        lazy="selectin",
    )
    labels = relationship(
        "Label",
        secondary=ticket_labels,
        back_populates="tickets",
        lazy="selectin",
    )
    comments = relationship(
        "Comment",
        back_populates="ticket",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    time_entries = relationship(
        "TimeEntry",
        back_populates="ticket",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Ticket(id={self.id!r}, title={self.title!r}, status={self.status!r})>"