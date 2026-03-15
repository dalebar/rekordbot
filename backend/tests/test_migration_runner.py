"""Tests for the database migration runner."""

import pytest
from alembic.util.exc import CommandError  # type: ignore[import-not-found]
from sqlalchemy import create_engine, inspect, text

from backend.models import crate, preference_rule, set_plan, track  # noqa: F401
from backend.models.database import Base
from backend.services.migration_runner import (
    get_alembic_ini_path,
    get_current_revision,
    has_alembic_version_table,
    run_migrations,
)

# The baseline migration revision ID from 001_baseline.py
BASELINE_REVISION = "baec48901c74"


@pytest.fixture
def fresh_engine(tmp_path):
    """Create a fresh SQLite engine with no tables."""
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_path}")
    yield engine
    engine.dispose()


@pytest.fixture
def pre_alembic_engine(tmp_path):
    """Create a SQLite engine with app tables but no alembic_version (pre-Alembic DB)."""
    db_path = tmp_path / "pre_alembic.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def migrated_engine(tmp_path):
    """Create a SQLite engine that has already been migrated."""
    db_path = tmp_path / "migrated.db"
    engine = create_engine(f"sqlite:///{db_path}")
    run_migrations(engine)
    yield engine
    engine.dispose()


class TestGetAlembicIniPath:
    """Tests for get_alembic_ini_path()."""

    def test_finds_ini_in_dev_mode(self):
        """In dev mode, alembic.ini should be found relative to the module."""
        path = get_alembic_ini_path()
        assert path.endswith("alembic.ini")
        assert "backend" in path


class TestHasAlembicVersionTable:
    """Tests for has_alembic_version_table()."""

    def test_fresh_db_has_no_version_table(self, fresh_engine):
        """A fresh database should have no alembic_version table."""
        assert has_alembic_version_table(fresh_engine) is False

    def test_pre_alembic_db_has_no_version_table(self, pre_alembic_engine):
        """A pre-Alembic database (create_all) should have no alembic_version table."""
        assert has_alembic_version_table(pre_alembic_engine) is False

    def test_migrated_db_has_version_table(self, migrated_engine):
        """A migrated database should have an alembic_version table."""
        assert has_alembic_version_table(migrated_engine) is True


class TestRunMigrations:
    """Tests for run_migrations() — the core branching logic."""

    def test_fresh_db_creates_all_tables(self, fresh_engine):
        """On a fresh DB, run_migrations should create all tables via Alembic."""
        run_migrations(fresh_engine)

        inspector = inspect(fresh_engine)
        table_names = set(inspector.get_table_names())
        expected = {
            "tracks",
            "crates",
            "crate_tracks",
            "set_plans",
            "set_tracks",
            "set_segments",
            "preference_rules",
            "alembic_version",
        }
        assert expected.issubset(table_names)

    def test_fresh_db_sets_revision(self, fresh_engine):
        """After migrating a fresh DB, the revision should be set."""
        run_migrations(fresh_engine)
        assert get_current_revision(fresh_engine) == BASELINE_REVISION

    def test_pre_alembic_db_stamps_without_modifying_tables(self, pre_alembic_engine):
        """A pre-Alembic DB should be stamped, preserving existing tables."""
        # Verify tables exist before migration
        inspector = inspect(pre_alembic_engine)
        tables_before = set(inspector.get_table_names())
        assert "tracks" in tables_before

        # Insert a test row to confirm data is preserved
        with pre_alembic_engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO tracks (file_path, quality_warning, rating, "
                    "analysis_status, ai_status, organisation_status, date_added, "
                    "date_modified, play_count, conversion_status) "
                    "VALUES ('/test.aiff', 0, 0, 'unanalysed', 'untagged', "
                    "'unorganised', '2026-01-01', '2026-01-01', 0, 'pending')"
                )
            )
            conn.commit()

        run_migrations(pre_alembic_engine)

        # Verify revision is set
        assert get_current_revision(pre_alembic_engine) == BASELINE_REVISION

        # Verify data is preserved
        with pre_alembic_engine.connect() as conn:
            result = conn.execute(text("SELECT file_path FROM tracks"))
            row = result.fetchone()
            assert row[0] == "/test.aiff"

    def test_already_migrated_db_is_noop(self, migrated_engine):
        """Running migrations on an already-migrated DB should be a no-op."""
        revision_before = get_current_revision(migrated_engine)

        # Run again — should not error
        run_migrations(migrated_engine)

        revision_after = get_current_revision(migrated_engine)
        assert revision_before == revision_after

    def test_migration_error_is_raised(self, tmp_path):
        """If migration fails, the error should be re-raised."""
        # Use a read-only path to trigger an error
        db_path = tmp_path / "error.db"
        engine = create_engine(f"sqlite:///{db_path}")

        # Create the alembic_version table with an invalid revision
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('nonexistent_rev')")
            )
            conn.commit()

        # This should raise because 'nonexistent_rev' is not a valid revision
        with pytest.raises((CommandError, Exception)):
            run_migrations(engine)

        engine.dispose()


class TestGetCurrentRevision:
    """Tests for get_current_revision()."""

    def test_returns_none_for_fresh_db(self, fresh_engine):
        """A fresh DB should return None for current revision."""
        assert get_current_revision(fresh_engine) is None

    def test_returns_revision_after_migration(self, migrated_engine):
        """After migration, should return the baseline revision."""
        assert get_current_revision(migrated_engine) == BASELINE_REVISION
