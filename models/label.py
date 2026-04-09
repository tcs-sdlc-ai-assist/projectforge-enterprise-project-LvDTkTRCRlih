import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base


class Label(Base):
    __tablename__ = "labels"

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_label_project_name"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(100), nullable=False)
    color = Column(String(7), nullable=False, default="#3b82f6")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="labels", lazy="selectin")
    tickets = relationship(
        "Ticket",
        secondary="ticket_labels",
        back_populates="labels",
        lazy="selectin",
    )