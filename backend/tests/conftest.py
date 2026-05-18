"""Shared test fixtures for rekordbot backend tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom CLI options for pytest."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Overwrite golden expected output files with actual rendered output. "
        "For developer use only — never run in CI.",
    )


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    """Whether the test should overwrite its golden file instead of comparing."""
    return bool(request.config.getoption("--update-golden"))


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

    # Drop and recreate all tables to pick up schema changes
    from backend.models.database import engine as prod_engine
    from backend.models.track import Track

    Base.metadata.drop_all(prod_engine)
    init_db()

    # Clean tables for test isolation
    from backend.models.crate import Crate, CrateTrack
    from backend.models.set_plan import SetPlan, SetSegment, SetTrack

    db = SessionLocal()
    db.query(SetTrack).delete()
    db.query(SetSegment).delete()
    db.query(SetPlan).delete()
    db.query(CrateTrack).delete()
    db.query(Crate).delete()
    db.query(Track).delete()
    db.commit()
    db.close()

    # Reset module-level queue state between tests
    import backend.routes.ai_tagging as ai_tagging_module
    import backend.routes.crates as crates_module
    import backend.routes.export as export_module
    import backend.routes.import_xml as import_xml_module
    import backend.routes.ingest as ingest_module
    import backend.routes.organise as organise_module
    import backend.routes.sets as sets_module
    import backend.routes.tagging as tagging_module

    ingest_module._queue = None
    tagging_module._analysis_queue = None
    ai_tagging_module._ai_tagger = None
    organise_module._organiser = None
    export_module._last_export = None
    crates_module._assigner = None
    sets_module._planner = None
    import_xml_module._import_in_progress = False
    import_xml_module._cancel_event = None
    import_xml_module._last_progress = None
    import_xml_module._last_summary = None
    import_xml_module._progress_queue = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
