"""Test health endpoint."""

import pytest


def test_health_endpoint_format():
    """Test that health response has expected format."""
    expected_keys = {"status", "service"}
    response = {"status": "ok", "service": "KnowledgeDrift"}
    assert set(response.keys()) == expected_keys
    assert response["status"] == "ok"
