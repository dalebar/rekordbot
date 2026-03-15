"""Automatic database migration runner for application startup.

Detects the database state and runs the appropriate Alembic command:
- Fresh DB (no tables): run ``alembic upgrade head`` to create all tables.
- Pre-Alembic DB (tables exist but no ``alembic_version``): stamp as current.
- Already-migrated DB (``alembic_version`` exists): run ``upgrade head`` (no-op if current).
"""

import logging
import sys
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def get_alembic_ini_path() -> str:
    """Resolve the path to alembic.ini for both dev and packaged mode.

    In dev mode, alembic.ini is at ``backend/alembic.ini`` relative to this file's
    grandparent. In packaged mode (PyInstaller), it's inside ``sys._MEIPASS``.

    Returns:
        Absolute path to alembic.ini.

    Raises:
        FileNotFoundError: If alembic.ini cannot be found.
    """
    # PyInstaller packaged mode: files are extracted to sys._MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        packaged_path = Path(meipass) / "backend" / "alembic.ini"
        if packaged_path.exists():
            return str(packaged_path)

    # Dev mode: relative to this file (backend/services/migration_runner.py)
    dev_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    if dev_path.exists():
        return str(dev_path)

    raise FileNotFoundError("Cannot find alembic.ini in dev or packaged mode")


def has_alembic_version_table(engine: Engine) -> bool:
    """Check whether the ``alembic_version`` table exists in the database.

    Args:
        engine: SQLAlchemy engine connected to the target database.

    Returns:
        True if the ``alembic_version`` table exists.
    """
    inspector = inspect(engine)
    return "alembic_version" in inspector.get_table_names()


def _has_any_app_tables(engine: Engine) -> bool:
    """Check whether any application tables exist (pre-Alembic database).

    Args:
        engine: SQLAlchemy engine connected to the target database.

    Returns:
        True if at least one application table exists.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    app_tables = {
        "tracks",
        "crates",
        "crate_tracks",
        "set_plans",
        "set_tracks",
        "set_segments",
        "preference_rules",
    }
    return bool(table_names & app_tables)


def run_migrations(engine: Engine) -> None:
    """Detect database state and run the appropriate Alembic migration command.

    Three cases:
    1. **Fresh DB** — no app tables, no alembic_version → ``upgrade head``
    2. **Pre-Alembic DB** — app tables exist but no alembic_version → ``stamp head``
    3. **Already-migrated DB** — alembic_version exists → ``upgrade head`` (no-op if current)

    Args:
        engine: SQLAlchemy engine connected to the target database.

    Raises:
        Exception: Re-raises any migration error after logging it.
    """
    from alembic import command  # type: ignore[import-not-found]
    from alembic.config import Config  # type: ignore[import-not-found]

    ini_path = get_alembic_ini_path()
    alembic_cfg = Config(ini_path)

    # Override the DB URL to match the engine's actual URL
    alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))

    has_version_table = has_alembic_version_table(engine)
    has_app_tables = _has_any_app_tables(engine)

    try:
        if has_version_table:
            # Case 3: Already-migrated DB — upgrade to latest (no-op if current)
            logger.info("Database has alembic_version table — running upgrade")
            command.upgrade(alembic_cfg, "head")
        elif has_app_tables:
            # Case 2: Pre-Alembic DB — stamp as current without modifying tables
            logger.info("Pre-Alembic database detected — stamping as current")
            command.stamp(alembic_cfg, "head")
        else:
            # Case 1: Fresh DB — create all tables via migration
            logger.info("Fresh database — running initial migration")
            command.upgrade(alembic_cfg, "head")
    except Exception:
        logger.exception("Database migration failed")
        raise


def get_current_revision(engine: Engine) -> str | None:
    """Read the current Alembic revision from the database.

    Args:
        engine: SQLAlchemy engine connected to the target database.

    Returns:
        The current revision string, or None if no revision is stamped.
    """
    if not has_alembic_version_table(engine):
        return None

    with engine.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        return row[0] if row else None
