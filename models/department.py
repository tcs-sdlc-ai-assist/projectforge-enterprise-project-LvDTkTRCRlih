import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from database import Base


class Department(Base):
    __tablename__ = "departments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    head_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    head = relationship(
        "User",
        foreign_keys=[head_id],
        back_populates="headed_department",
        lazy="selectin",
    )

    members = relationship(
        "User",
        foreign_keys="[User.department_id]",
        back_populates="department",
        lazy="selectin",
    )

    projects = relationship(
        "Project",
        back_populates="department",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Department(id={self.id}, name={self.name})>"