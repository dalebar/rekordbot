"""Tests for import_source and import_conflicts fields on the Track model."""

import json

from backend.models.track import Track


class TestTrackImportFields:
    """Test the Phase 4b import fields on the Track model."""

    def test_import_source_defaults_to_none(self, db_session):
        """New tracks should have import_source=None by default."""
        track = Track(file_path="/test/track.aiff")
        db_session.add(track)
        db_session.flush()

        fetched = db_session.query(Track).get(track.id)
        assert fetched.import_source is None

    def test_import_source_set_to_rekordbox_xml(self, db_session):
        """Imported tracks should have import_source='rekordbox_xml'."""
        track = Track(
            file_path="/test/imported.aiff",
            import_source="rekordbox_xml",
        )
        db_session.add(track)
        db_session.flush()

        fetched = db_session.query(Track).get(track.id)
        assert fetched.import_source == "rekordbox_xml"

    def test_import_conflicts_defaults_to_none(self, db_session):
        """New tracks should have import_conflicts=None by default."""
        track = Track(file_path="/test/track2.aiff")
        db_session.add(track)
        db_session.flush()

        fetched = db_session.query(Track).get(track.id)
        assert fetched.import_conflicts is None

    def test_import_conflicts_stores_json(self, db_session):
        """import_conflicts should store JSON conflict data."""
        conflicts = [
            {
                "field": "bpm",
                "rekordbox_value": 128.0,
                "rekordbot_value": 127.5,
                "recommended": "rekordbox",
            },
            {
                "field": "genre",
                "rekordbox_value": "Deep House",
                "rekordbot_value": "House",
                "recommended": "rekordbox",
            },
        ]
        track = Track(
            file_path="/test/conflict.aiff",
            import_conflicts=json.dumps(conflicts),
        )
        db_session.add(track)
        db_session.flush()

        fetched = db_session.query(Track).get(track.id)
        assert fetched.import_conflicts is not None
        parsed = json.loads(fetched.import_conflicts)
        assert len(parsed) == 2
        assert parsed[0]["field"] == "bpm"
        assert parsed[1]["rekordbox_value"] == "Deep House"

    def test_import_conflicts_clearable(self, db_session):
        """import_conflicts should be clearable by setting to None."""
        track = Track(
            file_path="/test/resolved.aiff",
            import_conflicts='[{"field": "bpm"}]',
        )
        db_session.add(track)
        db_session.flush()

        track.import_conflicts = None
        db_session.flush()

        fetched = db_session.query(Track).get(track.id)
        assert fetched.import_conflicts is None
