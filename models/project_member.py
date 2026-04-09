import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class ProjectMember(Base):
    __tablename__ = "project_members"

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member_project_user"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(
        Enum("owner", "manager", "member", "observer", name="project_member_role"),
        nullable=False,
        default="member",
    )
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    project = relationship("Project", back_populates="members", lazy="selectin")
    user = relationship("User", back_populates="project_memberships", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<ProjectMember(id={self.id!r}, project_id={self.project_id!r}, "
            f"user_id={self.user_id!r}, role={self.role!r})>"
        )