"""Tests for standardised error handling."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def error_client():
    """Async HTTP client for testing error handling."""
    from backend.main import app
    from backend.models.database import init_db

    init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestValidationErrorHandler:
    """Tests for RequestValidationError handling."""

    @pytest.mark.asyncio
    async def test_validation_error_returns_standard_format(
        self, error_client: AsyncClient
    ) -> None:
        """Sending invalid body to a typed endpoint returns standard error JSON."""
        resp = await error_client.put(
            "/api/settings",
            json={"organise_confidence_threshold": "not_a_number"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data
        assert data["error"] == "validation_error"
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_validation_error_for_out_of_range(self, error_client: AsyncClient) -> None:
        """Sending out-of-range value returns validation error."""
        resp = await error_client.put(
            "/api/settings",
            json={"organise_confidence_threshold": 2.0},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"] == "validation_error"


class TestUnhandledExceptionMiddleware:
    """Tests for the unhandled exception catch-all."""

    @pytest.mark.asyncio
    async def test_404_returns_standard_format(self, error_client: AsyncClient) -> None:
        """Non-existent routes return JSON, not HTML."""
        resp = await error_client.get("/api/nonexistent")
        assert resp.status_code in (404, 405)
        # FastAPI returns its own 404 JSON — verify it's JSON, not HTML
        data = resp.json()
        assert "detail" in data


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, error_client: AsyncClient) -> None:
        resp = await error_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
