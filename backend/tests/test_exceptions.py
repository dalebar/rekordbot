"""Tests for the exception handling system."""

from fastapi import APIRouter

from backend.exceptions import RekordBotError
from backend.main import app

# Register temporary test routes for exception testing
_test_router = APIRouter()


@_test_router.get("/test/known-error")
async def raise_known_error():
    """Raise a known RekordBotError for testing."""
    raise RekordBotError(error="test_error", detail="This is a test error", status_code=422)


@_test_router.get("/test/unexpected-error")
async def raise_unexpected_error():
    """Raise an unexpected exception for testing."""
    raise RuntimeError("Something went wrong unexpectedly")


app.include_router(_test_router)


async def test_known_error_returns_json(client):
    """RekordBotError is caught and returned as structured JSON."""
    response = await client.get("/test/known-error")
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "test_error"
    assert data["detail"] == "This is a test error"


async def test_unexpected_error_returns_500(client):
    """Unhandled exceptions return a generic 500 response."""
    response = await client.get("/test/unexpected-error")
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "internal_error"
    assert "unexpected" in data["detail"].lower()
