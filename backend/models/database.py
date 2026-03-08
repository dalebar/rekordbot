"""SQLAlchemy database engine, session factory, and declarative base."""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(settings.db_url, echo=False)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""


def init_db() -> None:
    """Create all tables defined by Base subclasses."""
    from backend.models import (  # noqa: F401 — ensure models registered
        crate,
        preference_rule,
        track,
    )

    Base.metadata.create_all(engine)
    logger.info("Database tables created")
