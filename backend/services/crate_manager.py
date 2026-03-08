"""Crate manager — high-level CRUD and orchestration for crates.

Coordinates crate creation, update, deletion, refresh, and manual
track management. This is the service layer that API routes call.
"""

import contextlib
import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.exceptions import CrateError
from backend.models.crate import Crate, CrateTrack
from backend.models.track import Track
from backend.services.claude_client import ClaudeClient
from backend.services.crate_assigner import AssignmentResult, CrateAssigner
from backend.services.crate_prompt_builder import (
    build_criteria_prompt,
    parse_criteria_result,
)

logger = logging.getLogger(__name__)


@dataclass
class CrateSummary:
    """Crate with track count for listing.

    Attributes:
        id: Crate database ID.
        name: Crate display name.
        description: Original description.
        track_count: Number of tracks assigned.
        auto_refresh: Whether auto-refresh is enabled.
        created_at: Creation timestamp ISO string.
        updated_at: Last modified timestamp ISO string.
    """

    id: int
    name: str
    description: str
    track_count: int
    auto_refresh: bool
    created_at: str
    updated_at: str


@dataclass
class CrateDetail:
    """Full crate detail including track list.

    Attributes:
        id: Crate database ID.
        name: Crate display name.
        description: Original description.
        parsed_criteria: Parsed criteria dict (or None).
        auto_refresh: Whether auto-refresh is enabled.
        track_ids: List of assigned track IDs.
        track_count: Number of tracks assigned.
        created_at: Creation timestamp ISO string.
        updated_at: Last modified timestamp ISO string.
    """

    id: int
    name: str
    description: str
    parsed_criteria: dict | None
    auto_refresh: bool
    track_ids: list[int]
    track_count: int
    created_at: str
    updated_at: str


def list_crates(db_session: Session) -> list[CrateSummary]:
    """List all crates with track counts.

    Args:
        db_session: SQLAlchemy session.

    Returns:
        List of CrateSummary objects.
    """
    crates = db_session.query(Crate).all()
    result = []
    for crate in crates:
        count = db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate.id).count()
        result.append(
            CrateSummary(
                id=crate.id,
                name=crate.name,
                description=crate.description,
                track_count=count,
                auto_refresh=crate.auto_refresh,
                created_at=crate.created_at.isoformat(),
                updated_at=crate.updated_at.isoformat(),
            )
        )
    return result


def get_crate(crate_id: int, db_session: Session) -> CrateDetail:
    """Get full crate detail including track list.

    Args:
        crate_id: Crate database ID.
        db_session: SQLAlchemy session.

    Returns:
        CrateDetail with full information.

    Raises:
        CrateError: If crate not found.
    """
    crate = db_session.query(Crate).filter(Crate.id == crate_id).first()
    if crate is None:
        raise CrateError(f"Crate {crate_id} not found", status_code=404)

    track_ids = [
        ct.track_id
        for ct in db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate_id).all()
    ]

    parsed = None
    if crate.parsed_criteria:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            parsed = json.loads(crate.parsed_criteria)

    return CrateDetail(
        id=crate.id,
        name=crate.name,
        description=crate.description,
        parsed_criteria=parsed,
        auto_refresh=crate.auto_refresh,
        track_ids=track_ids,
        track_count=len(track_ids),
        created_at=crate.created_at.isoformat(),
        updated_at=crate.updated_at.isoformat(),
    )


def create_crate(
    name: str,
    description: str,
    auto_refresh: bool,
    db_session: Session,
) -> Crate:
    """Create a new crate record (without assignment).

    Args:
        name: Display name.
        description: Free-text description.
        auto_refresh: Whether to auto-refresh on new ingestion.
        db_session: SQLAlchemy session.

    Returns:
        The created Crate model instance.
    """
    crate = Crate(name=name, description=description, auto_refresh=auto_refresh)
    db_session.add(crate)
    db_session.commit()
    logger.info("Created crate %d: %s", crate.id, name)
    return crate


async def parse_description(
    crate: Crate,
    db_session: Session,
    settings: Settings,
) -> dict:
    """Parse a crate description into structured criteria via Claude.

    Args:
        crate: The crate with a description to parse.
        db_session: SQLAlchemy session.
        settings: Application settings.

    Returns:
        Parsed criteria dict.
    """
    import asyncio

    claude_client = ClaudeClient(
        api_key=settings.anthropic_api_key,
        model=settings.ai_model,
        max_requests_per_minute=settings.ai_max_requests_per_minute,
    )

    system_prompt, user_message, tool_schema = build_criteria_prompt(crate.description)

    await claude_client.rate_limiter.acquire()
    response = await asyncio.to_thread(
        claude_client.client.messages.create,
        model=claude_client.model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        tools=[tool_schema],
        tool_choice={"type": "tool", "name": "parse_crate_criteria"},
    )

    # Extract tool result
    criteria = {}
    for block in response.content:
        if block.type == "tool_use" and block.name == "parse_crate_criteria":
            criteria = parse_criteria_result(block.input)
            break

    crate.parsed_criteria = json.dumps(criteria)
    db_session.commit()
    logger.info("Parsed criteria for crate %d", crate.id)
    return criteria


def update_crate(
    crate_id: int,
    db_session: Session,
    name: str | None = None,
    description: str | None = None,
    auto_refresh: bool | None = None,
) -> tuple[Crate, bool]:
    """Update a crate's name, description, or auto_refresh flag.

    Args:
        crate_id: Crate database ID.
        db_session: SQLAlchemy session.
        name: New name (or None to keep existing).
        description: New description (or None to keep existing).
        auto_refresh: New auto_refresh flag (or None to keep existing).

    Returns:
        Tuple of (updated Crate, description_changed: bool).

    Raises:
        CrateError: If crate not found.
    """
    crate = db_session.query(Crate).filter(Crate.id == crate_id).first()
    if crate is None:
        raise CrateError(f"Crate {crate_id} not found", status_code=404)

    description_changed = False
    if name is not None:
        crate.name = name
    if description is not None and description != crate.description:
        crate.description = description
        description_changed = True
    if auto_refresh is not None:
        crate.auto_refresh = auto_refresh

    db_session.commit()
    logger.info("Updated crate %d", crate_id)
    return crate, description_changed


def delete_crate(crate_id: int, db_session: Session) -> None:
    """Delete a crate and all its track assignments.

    Args:
        crate_id: Crate database ID.
        db_session: SQLAlchemy session.

    Raises:
        CrateError: If crate not found.
    """
    crate = db_session.query(Crate).filter(Crate.id == crate_id).first()
    if crate is None:
        raise CrateError(f"Crate {crate_id} not found", status_code=404)

    db_session.delete(crate)
    db_session.commit()
    logger.info("Deleted crate %d", crate_id)


def add_tracks(
    crate_id: int,
    track_ids: list[int],
    db_session: Session,
) -> int:
    """Manually add tracks to a crate.

    Args:
        crate_id: Crate database ID.
        track_ids: Track IDs to add.
        db_session: SQLAlchemy session.

    Returns:
        Number of tracks actually added (excludes already-present).

    Raises:
        CrateError: If crate not found.
    """
    crate = db_session.query(Crate).filter(Crate.id == crate_id).first()
    if crate is None:
        raise CrateError(f"Crate {crate_id} not found", status_code=404)

    existing = {
        ct.track_id
        for ct in db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate_id).all()
    }

    added = 0
    for track_id in track_ids:
        if track_id not in existing:
            db_session.add(
                CrateTrack(
                    crate_id=crate_id,
                    track_id=track_id,
                    assignment_method="manual",
                )
            )
            added += 1

    db_session.commit()
    logger.info("Added %d tracks manually to crate %d", added, crate_id)
    return added


def remove_tracks(
    crate_id: int,
    track_ids: list[int],
    db_session: Session,
) -> int:
    """Remove tracks from a crate.

    Args:
        crate_id: Crate database ID.
        track_ids: Track IDs to remove.
        db_session: SQLAlchemy session.

    Returns:
        Number of tracks removed.

    Raises:
        CrateError: If crate not found.
    """
    crate = db_session.query(Crate).filter(Crate.id == crate_id).first()
    if crate is None:
        raise CrateError(f"Crate {crate_id} not found", status_code=404)

    removed = (
        db_session.query(CrateTrack)
        .filter(
            CrateTrack.crate_id == crate_id,
            CrateTrack.track_id.in_(track_ids),
        )
        .delete(synchronize_session="fetch")
    )
    db_session.commit()
    logger.info("Removed %d tracks from crate %d", removed, crate_id)
    return removed


async def refresh_crate(
    crate_id: int,
    db_session: Session,
    settings: Settings,
    assigner: CrateAssigner,
) -> AssignmentResult:
    """Refresh a crate by re-running AI assignment.

    Clears existing AI assignments, preserves manual ones,
    then re-assigns all tracks.

    Args:
        crate_id: Crate database ID.
        db_session: SQLAlchemy session.
        settings: Application settings.
        assigner: CrateAssigner instance (for SSE events).

    Returns:
        AssignmentResult from the new assignment.

    Raises:
        CrateError: If crate not found.
    """
    crate = db_session.query(Crate).filter(Crate.id == crate_id).first()
    if crate is None:
        raise CrateError(f"Crate {crate_id} not found", status_code=404)

    # Clear AI assignments
    assigner.clear_ai_assignments(crate_id, db_session)

    # Load all tracks
    tracks = db_session.query(Track).all()

    # Create Claude client
    claude_client = ClaudeClient(
        api_key=settings.anthropic_api_key,
        model=settings.ai_model,
        max_requests_per_minute=settings.ai_max_requests_per_minute,
    )

    return await assigner.assign_tracks(crate, tracks, db_session, claude_client)


async def auto_refresh_crates(
    track_ids: list[int],
    db_session: Session,
    settings: Settings,
) -> None:
    """Run assignment on auto-refresh crates for newly ingested tracks.

    Args:
        track_ids: IDs of newly ingested tracks.
        db_session: SQLAlchemy session.
        settings: Application settings.
    """
    crates = db_session.query(Crate).filter(Crate.auto_refresh.is_(True)).all()
    if not crates:
        return

    tracks = db_session.query(Track).filter(Track.id.in_(track_ids)).all()
    if not tracks:
        return

    claude_client = ClaudeClient(
        api_key=settings.anthropic_api_key,
        model=settings.ai_model,
        max_requests_per_minute=settings.ai_max_requests_per_minute,
    )

    for crate in crates:
        assigner = CrateAssigner(settings)
        try:
            result = await assigner.assign_tracks(crate, tracks, db_session, claude_client)
            logger.info(
                "Auto-refresh crate %d: %d/%d tracks matched",
                crate.id,
                result.matched,
                result.total_tracks,
            )
        except Exception:
            logger.exception("Auto-refresh failed for crate %d", crate.id)
