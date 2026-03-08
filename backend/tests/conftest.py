"""Shared test fixtures for rekordbot backend tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base


@pytest.fixture(scope="session")
def engine():
    """Create an in-memory SQLite engine for the test session."""
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine):
    """Create a fresh database session for each test, rolled back after."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    from backend.main import app
    from backend.models.database import SessionLocal, init_db
    from backend.models.track import Track

    # Ensure tables exist (lifespan doesn't run with ASGITransport)
    init_db()

    # Clean tracks table for test isolation
    db = SessionLocal()
    db.query(Track).delete()
    db.commit()
    db.close()

    # Reset module-level queue state between tests
    import backend.routes.ai_tagging as ai_tagging_module
    import backend.routes.ingest as ingest_module
    import backend.routes.organise as organise_module
    import backend.routes.tagging as tagging_module

    ingest_module._queue = None
    tagging_module._analysis_queue = None
    ai_tagging_module._ai_tagger = None
    organise_module._organiser = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
