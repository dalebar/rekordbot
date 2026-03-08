"""Tests for SQLAlchemy models."""

from backend.models.track import Track


def test_track_create_and_query(db_session):
    """Track can be created, saved, and queried."""
    track = Track(
        file_path="/music/test-track.aiff",
        title="Test Track",
        artist="Test Artist",
        bpm=128.00,
    )
    db_session.add(track)
    db_session.flush()

    result = db_session.query(Track).filter_by(file_path="/music/test-track.aiff").one()
    assert result.title == "Test Track"
    assert result.artist == "Test Artist"
    assert result.bpm == 128.00
    assert result.rating == 0
    assert result.conversion_status == "pending"
    assert result.organisation_status == "unorganised"
    assert result.date_added is not None
    assert result.ai_status == "untagged"


def test_track_ai_columns(db_session):
    """Track AI enrichment columns can be set and queried."""
    track = Track(
        file_path="/music/ai-test.aiff",
        title="AI Test",
        artist="Test Artist",
        genre="Electronic",
    )
    db_session.add(track)
    db_session.flush()

    # Update with AI tag results
    track.subgenre = "Melodic Techno"
    track.mood = "Euphoric"
    track.energy = 7
    track.ai_confidence = "high"
    track.ai_reasoning = "Recognised artist is a melodic techno producer."
    track.source_genre = "Electronic"
    track.genre = "Melodic Techno"
    track.ai_status = "ai_tagged"
    db_session.flush()

    result = db_session.query(Track).filter_by(file_path="/music/ai-test.aiff").one()
    assert result.genre == "Melodic Techno"
    assert result.subgenre == "Melodic Techno"
    assert result.mood == "Euphoric"
    assert result.energy == 7
    assert result.ai_confidence == "high"
    assert result.ai_reasoning == "Recognised artist is a melodic techno producer."
    assert result.source_genre == "Electronic"
    assert result.ai_status == "ai_tagged"


def test_track_unique_file_path(db_session):
    """Duplicate file_path raises an integrity error."""
    track1 = Track(file_path="/music/unique.aiff", title="Track 1")
    track2 = Track(file_path="/music/unique.aiff", title="Track 2")
    db_session.add(track1)
    db_session.flush()
    db_session.add(track2)

    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_track_repr(db_session):
    """Track repr shows id, artist, and title."""
    track = Track(file_path="/music/repr-test.aiff", artist="DJ Test", title="Bangerz")
    db_session.add(track)
    db_session.flush()

    assert "DJ Test" in repr(track)
    assert "Bangerz" in repr(track)
