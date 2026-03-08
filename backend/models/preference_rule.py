"""PreferenceRule model — stores user-created organisation preferences."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.database import Base


class PreferenceRule(Base):
    """A user-defined rule for file organisation decisions.

    Rule types:
        - artist_folder: Canonical folder name for an artist.
        - va_handling: Strategy for VA compilation tracks.
        - custom_path: Explicit override path for a specific track.

    Keys are normalised to lowercase with whitespace trimmed
    for consistent case-insensitive matching.
    """

    __tablename__ = "preference_rules"
    __table_args__ = (UniqueConstraint("rule_type", "key", name="uq_rule_type_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:
        return (
            f"<PreferenceRule(id={self.id}, type={self.rule_type!r}, "
            f"key={self.key!r}, value={self.value!r})>"
        )
