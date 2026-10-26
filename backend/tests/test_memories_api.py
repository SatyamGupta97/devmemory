"""API-level tests: validation, status codes and response shape."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

VALID_MEMORY = {
    "content": "Never log full card numbers or CVV values.",
    "category": "constraint",
    "source": "security-guideline",
    "project": "payments-api",
    "confidence": 1.0,
}


def test_create_memory_returns_201_and_the_stored_record(
    client: TestClient,
) -> None:
    response = client.post("/api/memories", json=VALID_MEMORY)

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == VALID_MEMORY["content"]
    assert body["category"] == "constraint"
    assert body["project"] == "payments-api"
    assert body["confidence"] == 1.0
    assert body["status"] == "active"
    assert body["superseded_by"] is None
    assert body["id"]
    assert body["created_at"] == body["updated_at"]


def test_created_memory_appears_in_the_list(client: TestClient) -> None:
    created = client.post("/api/memories", json=VALID_MEMORY).json()

    listed = client.get("/api/memories")

    assert listed.status_code == 200
    assert [memory["id"] for memory in listed.json()] == [created["id"]]


def test_list_is_empty_before_any_writes(client: TestClient) -> None:
    response = client.get("/api/memories")

    assert response.status_code == 200
    assert response.json() == []


def test_whitespace_is_trimmed(client: TestClient) -> None:
    response = client.post(
        "/api/memories", json={**VALID_MEMORY, "content": "  Use request IDs.  "}
    )

    assert response.status_code == 201
    assert response.json()["content"] == "Use request IDs."


def test_confidence_is_optional(client: TestClient) -> None:
    payload = {key: value for key, value in VALID_MEMORY.items() if key != "confidence"}

    response = client.post("/api/memories", json=payload)

    assert response.status_code == 201
    assert response.json()["confidence"] is None


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("content", ""),
        ("content", "   "),
        ("content", None),
        ("category", "vibes"),
        ("project", ""),
        ("source", ""),
        ("confidence", 1.5),
        ("confidence", -0.1),
    ],
)
def test_invalid_input_is_rejected(
    client: TestClient, field: str, bad_value: object
) -> None:
    response = client.post("/api/memories", json={**VALID_MEMORY, field: bad_value})

    assert response.status_code == 422
    # The error must name the offending field so the caller can fix it.
    assert field in json.dumps(response.json())


def test_missing_required_field_is_rejected(client: TestClient) -> None:
    payload = {key: value for key, value in VALID_MEMORY.items() if key != "project"}

    response = client.post("/api/memories", json=payload)

    assert response.status_code == 422
    assert "project" in json.dumps(response.json())


def test_overlong_content_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/memories", json={**VALID_MEMORY, "content": "x" * 4001}
    )

    assert response.status_code == 422


def test_rejected_input_stores_nothing(client: TestClient) -> None:
    client.post("/api/memories", json={**VALID_MEMORY, "content": ""})

    assert client.get("/api/memories").json() == []


def test_openapi_documents_the_memory_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "post" in paths["/api/memories"]
    assert "get" in paths["/api/memories"]


def test_sample_dataset_is_valid() -> None:
    """The demo data must satisfy the same schema users are held to."""
    from app.schemas import MemoryCreate

    sample_path = Path(__file__).resolve().parents[2] / "data" / "sample_memories.json"
    entries = json.loads(sample_path.read_text())

    assert len(entries) >= 10
    for entry in entries:
        MemoryCreate.model_validate(entry)
