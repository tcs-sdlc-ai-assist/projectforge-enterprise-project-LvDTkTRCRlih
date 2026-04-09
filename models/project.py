import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Table, Text
from sqlalchemy.orm import relationship

from database import Base

project_members = Table(
    "project_members",
    Base.metadata,
    Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    key = Column(String(10), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    department_id = Column(String(36), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(
        Enum("planning", "active", "on_hold", "completed", "archived", name="project_status"),
        nullable=False,
        default="planning",
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    department = relationship("Department", back_populates="projects", lazy="selectin")
    owner = relationship("User", back_populates="owned_projects", foreign_keys=[owner_id], lazy="selectin")
    members = relationship(
        "User",
        secondary=project_members,
        back_populates="projects",
        lazy="selectin",
    )
    sprints = relationship("Sprint", back_populates="project", lazy="selectin", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="project", lazy="selectin", cascade="all, delete-orphan")
    labels = relationship("Label", back_populates="project", lazy="selectin", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name}, key={self.key}, status={self.status})>"