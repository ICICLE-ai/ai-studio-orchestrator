"""Tests for application-level request handling."""

from fastapi.testclient import TestClient

from ai_studio.exceptions import UpstreamServiceError
from ai_studio.main import app


def test_service_error_handler_returns_structured_status():
    async def fail_with_service_error():
        raise UpstreamServiceError(
            status_code=409,
            detail={
                "message": "Provisioned resource conflicts with requested config",
                "details": "already exists",
            },
        )

    app.add_api_route("/_test/service-error", fail_with_service_error)
    with TestClient(app) as client:
        response = client.get("/_test/service-error")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "message": "Provisioned resource conflicts with requested config",
            "details": "already exists",
        }
    }
