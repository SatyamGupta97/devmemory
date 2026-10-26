from fastapi.testclient import TestClient

from app.main import SERVICE_NAME, SERVICE_VERSION, app

client = TestClient(app)


def test_health_returns_200() -> None:
    response = client.get("/health")

    assert response.status_code == 200


def test_health_payload_reports_healthy_service() -> None:
    response = client.get("/health")

    assert response.json() == {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
    }


def test_openapi_docs_are_available() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
