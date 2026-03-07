"""Tests for the /health endpoint."""


async def test_health_returns_ok(client):
    """Health endpoint returns 200 with status and version."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
