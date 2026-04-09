import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    ticket_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hours: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    billable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    ticket = relationship(
        "Ticket",
        back_populates="time_entries",
        lazy="selectin",
    )
    user = relationship(
        "User",
        back_populates="time_entries",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<TimeEntry(id={self.id!r}, ticket_id={self.ticket_id!r}, hours={self.hours!r}, date={self.date!r})>"