"""Track model — full schema for Rekordbox-compatible track metadata."""

from datetime import date, datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.database import Base


class Track(Base):
    """A music track with all metadata needed for Rekordbox XML export."""

    __tablename__ = "tracks"
    __table_args__ = (Index("ix_tracks_file_hash", "file_hash", unique=True),)

    # Core identification
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Source file provenance (populated by ingestion in Phase 1)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_format: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_codec: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Audio properties
    output_format: Mapped[str | None] = mapped_column(Text, nullable=True)
    codec: Mapped[str | None] = mapped_column(Text, nullable=True)
    bit_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_lossy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    quality_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    conversion_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Metadata (populated by tagger in Phase 2, or read from source tags)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    artist: Mapped[str | None] = mapped_column(Text, nullable=True)
    album: Mapped[str | None] = mapped_column(Text, nullable=True)
    genre: Mapped[str | None] = mapped_column(Text, nullable=True)
    composer: Mapped[str | None] = mapped_column(Text, nullable=True)
    remixer: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    mix_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    grouping: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    key: Mapped[int | None] = mapped_column(Integer, nullable=True)
    key_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating: Mapped[int] = mapped_column(Integer, default=0)
    colour: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI enrichment (populated by Claude layer in Phase 3)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mood: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_genre: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_tags: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Operational
    date_added: Mapped[str] = mapped_column(Text, default=lambda: date.today().isoformat())
    date_modified: Mapped[str] = mapped_column(Text, default=lambda: date.today().isoformat())
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    last_played: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversion_status: Mapped[str] = mapped_column(Text, default="pending")
    organisation_status: Mapped[str] = mapped_column(Text, default="pending")

    def __repr__(self) -> str:
        return f"<Track(id={self.id}, artist={self.artist!r}, title={self.title!r})>"
