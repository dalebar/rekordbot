"""Crate and CrateTrack models — AI-powered smart playlists."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.database import Base


class Crate(Base):
    """A smart playlist created from a free-text description.

    Claude interprets the description into structured criteria and assigns
    matching tracks. Crates are unordered pools — a track can appear in
    multiple crates.
    """

    __tablename__ = "crates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_refresh: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    crate_tracks: Mapped[list["CrateTrack"]] = relationship(
        "CrateTrack", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Crate(id={self.id}, name={self.name!r})>"


class CrateTrack(Base):
    """Association between a crate and a track.

    Tracks can be assigned by AI (during crate creation/refresh) or
    manually by the user. Manual assignments are preserved during refresh.
    """

    __tablename__ = "crate_tracks"
    __table_args__ = (UniqueConstraint("crate_id", "track_id", name="uq_crate_track"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("crates.id", ondelete="CASCADE"), nullable=False
    )
    track_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False
    )
    assignment_method: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:
        return (
            f"<CrateTrack(crate_id={self.crate_id}, track_id={self.track_id}, "
            f"method={self.assignment_method!r})>"
        )
