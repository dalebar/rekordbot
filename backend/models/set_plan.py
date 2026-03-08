"""SetPlan, SetTrack, and SetSegment models — AI-powered set planning."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.database import Base


class SetPlan(Base):
    """A DJ set plan with ordered track sequence and segment descriptions.

    Sets are ordered sequences of tracks intended for playback in a specific
    order. They support lock-and-shuffle iterative refinement via Claude.
    """

    __tablename__ = "set_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_bpm_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_bpm_end: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_arc: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="library")
    source_crate_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    harmonic_mixing: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    set_tracks: Mapped[list["SetTrack"]] = relationship(
        "SetTrack", cascade="all, delete-orphan", passive_deletes=True
    )
    set_segments: Mapped[list["SetSegment"]] = relationship(
        "SetSegment", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<SetPlan(id={self.id}, name={self.name!r}, status={self.status!r})>"


class SetTrack(Base):
    """Association between a set and a track with position and lock state.

    Tracks in a set are either in the active sequence (is_candidate=False)
    or in the candidate pool (is_candidate=True). Active tracks have unique
    positions; candidates have position=0.
    """

    __tablename__ = "set_tracks"
    __table_args__ = (UniqueConstraint("set_id", "track_id", name="uq_set_track"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("set_plans.id", ondelete="CASCADE"), nullable=False
    )
    track_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    segment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("set_segments.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:
        return (
            f"<SetTrack(set_id={self.set_id}, track_id={self.track_id}, "
            f"pos={self.position}, locked={self.is_locked}, "
            f"candidate={self.is_candidate})>"
        )


class SetSegment(Base):
    """A segment within a set, defined by locked track boundaries.

    Segments are auto-calculated from locked track positions and hold
    per-segment mood descriptions for Claude to use during shuffle.
    """

    __tablename__ = "set_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("set_plans.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_track_position: Mapped[int] = mapped_column(Integer, nullable=False)
    end_track_position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def __repr__(self) -> str:
        return (
            f"<SetSegment(id={self.id}, set_id={self.set_id}, "
            f"pos={self.position}, range={self.start_track_position}-"
            f"{self.end_track_position})>"
        )
