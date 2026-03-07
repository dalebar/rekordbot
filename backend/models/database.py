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
    from backend.models import track  # noqa: F401 — ensure Track model is registered

    Base.metadata.create_all(engine)
    logger.info("Database tables created")
