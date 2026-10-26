"""CRUD, filtering and 404 behaviour over HTTP."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.services import memory_store

MEMORY = {
    "content": "The user service uses PostgreSQL 15 for persistence.",
    "category": "decision",
    "source": "architecture-review",
    "project": "payments-api",
    "confidence": 0.9,
}


def create(client: TestClient, **overrides: object) -> dict:
    response = client.post("/api/memories", json={**MEMORY, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_get_single_memory(client: TestClient) -> None:
    created = create(client)

    response = client.get(f"/api/memories/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_memory_returns_404(client: TestClient) -> None:
    response = client.get("/api/memories/does-not-exist")

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_patch_updates_only_the_given_field(client: TestClient) -> None:
    created = create(client)

    response = client.patch(
        f"/api/memories/{created['id']}", json={"content": "Now uses PostgreSQL 16."}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "Now uses PostgreSQL 16."
    # Untouched fields must survive a partial update.
    assert body["category"] == created["category"]
    assert body["project"] == created["project"]
    assert body["source"] == created["source"]
    assert body["confidence"] == created["confidence"]
    assert body["created_at"] == created["created_at"]


def test_patch_bumps_updated_at(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create(client)
    later = "2030-01-01T00:00:00+00:00"
    monkeypatch.setattr(memory_store, "utcnow_iso", lambda: later)

    patched = client.patch(
        f"/api/memories/{created['id']}", json={"content": "Changed."}
    ).json()

    # Compare parsed datetimes: JSON renders UTC as "Z" or "+00:00" depending on
    # the encoder, and both mean the same instant.
    assert datetime.fromisoformat(patched["updated_at"]) == datetime.fromisoformat(later)
    assert patched["created_at"] == created["created_at"]


def test_patch_can_clear_confidence(client: TestClient) -> None:
    created = create(client)

    response = client.patch(
        f"/api/memories/{created['id']}", json={"confidence": None}
    )

    assert response.status_code == 200
    assert response.json()["confidence"] is None


def test_patch_unknown_memory_returns_404(client: TestClient) -> None:
    response = client.patch("/api/memories/nope", json={"content": "x"})

    assert response.status_code == 404


def test_empty_patch_is_rejected(client: TestClient) -> None:
    created = create(client)

    response = client.patch(f"/api/memories/{created['id']}", json={})

    assert response.status_code == 422


def test_patch_cannot_null_a_required_field(client: TestClient) -> None:
    created = create(client)

    response = client.patch(f"/api/memories/{created['id']}", json={"content": None})

    assert response.status_code == 422


def test_patch_rejects_invalid_enum(client: TestClient) -> None:
    created = create(client)

    response = client.patch(
        f"/api/memories/{created['id']}", json={"category": "vibes"}
    )

    assert response.status_code == 422


def test_delete_removes_the_memory(client: TestClient) -> None:
    created = create(client)

    deleted = client.delete(f"/api/memories/{created['id']}")

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(f"/api/memories/{created['id']}").status_code == 404
    assert client.get("/api/memories").json() == []


def test_delete_unknown_memory_returns_404(client: TestClient) -> None:
    response = client.delete("/api/memories/nope")

    assert response.status_code == 404


def test_delete_of_a_referenced_replacement_returns_409(
    client: TestClient,
) -> None:
    """Regression: this used to raise a FK error and surface as HTTP 500.

    A 500 would blame the server for a request that is merely in conflict, and
    the caller would have no idea which memory blocked the delete.
    """
    old = create(client, content="Background jobs use Celery.")
    new = create(client, content="Background jobs use Dramatiq.")
    client.patch(
        f"/api/memories/{old['id']}",
        json={"status": "superseded", "superseded_by": new["id"]},
    )

    response = client.delete(f"/api/memories/{new['id']}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert old["id"] in detail
    # Nothing was destroyed, and the link is intact.
    assert client.get(f"/api/memories/{new['id']}").status_code == 200
    assert client.get(f"/api/memories/{old['id']}").json()["superseded_by"] == new["id"]


def test_replacement_can_be_deleted_once_the_reference_is_cleared(
    client: TestClient,
) -> None:
    old = create(client)
    new = create(client)
    client.patch(
        f"/api/memories/{old['id']}",
        json={"status": "superseded", "superseded_by": new["id"]},
    )
    client.patch(
        f"/api/memories/{old['id']}",
        json={"status": "active", "superseded_by": None},
    )

    response = client.delete(f"/api/memories/{new['id']}")

    assert response.status_code == 204


def test_list_filters_by_project(client: TestClient) -> None:
    payments = create(client, project="payments-api")
    create(client, project="analytics")

    response = client.get("/api/memories", params={"project": "payments-api"})

    assert [memory["id"] for memory in response.json()] == [payments["id"]]


def test_list_filters_by_category(client: TestClient) -> None:
    decision = create(client, category="decision")
    create(client, category="failure")

    response = client.get("/api/memories", params={"category": "decision"})

    assert [memory["id"] for memory in response.json()] == [decision["id"]]


def test_list_filters_combine(client: TestClient) -> None:
    match = create(client, project="payments-api", category="decision")
    create(client, project="payments-api", category="failure")
    create(client, project="analytics", category="decision")

    response = client.get(
        "/api/memories", params={"project": "payments-api", "category": "decision"}
    )

    assert [memory["id"] for memory in response.json()] == [match["id"]]


def test_list_rejects_unknown_category_filter(client: TestClient) -> None:
    response = client.get("/api/memories", params={"category": "vibes"})

    assert response.status_code == 422


def test_unknown_project_returns_empty_list(client: TestClient) -> None:
    """An empty namespace is a valid answer, not an error."""
    response = client.get("/api/memories", params={"project": "no-such-project"})

    assert response.status_code == 200
    assert response.json() == []


# --- supersede rules -------------------------------------------------------


def test_superseding_keeps_history_and_marks_the_old_decision(
    client: TestClient,
) -> None:
    old = create(client, content="Background jobs use Celery.")
    new = create(client, content="Background jobs use Dramatiq.")

    response = client.patch(
        f"/api/memories/{old['id']}",
        json={"status": "superseded", "superseded_by": new["id"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "superseded"
    assert body["superseded_by"] == new["id"]
    # The old decision is still stored and still readable.
    assert client.get(f"/api/memories/{old['id']}").status_code == 200
    assert client.get(f"/api/memories/{new['id']}").json()["status"] == "active"


def test_superseding_without_status_is_rejected(client: TestClient) -> None:
    old = create(client)
    new = create(client)

    response = client.patch(
        f"/api/memories/{old['id']}", json={"superseded_by": new["id"]}
    )

    assert response.status_code == 422
    assert "superseded" in response.json()["detail"]


def test_memory_cannot_supersede_itself(client: TestClient) -> None:
    created = create(client)

    response = client.patch(
        f"/api/memories/{created['id']}",
        json={"status": "superseded", "superseded_by": created["id"]},
    )

    assert response.status_code == 422
    assert "itself" in response.json()["detail"]


def test_superseding_an_unknown_memory_is_rejected(client: TestClient) -> None:
    created = create(client)

    response = client.patch(
        f"/api/memories/{created['id']}",
        json={"status": "superseded", "superseded_by": "ghost"},
    )

    assert response.status_code == 422
    assert "ghost" in response.json()["detail"]


def test_superseded_memory_can_be_reactivated(client: TestClient) -> None:
    old = create(client)
    new = create(client)
    client.patch(
        f"/api/memories/{old['id']}",
        json={"status": "superseded", "superseded_by": new["id"]},
    )

    response = client.patch(
        f"/api/memories/{old['id']}",
        json={"status": "active", "superseded_by": None},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert response.json()["superseded_by"] is None


def test_reactivation_without_clearing_replacement_is_rejected(
    client: TestClient,
) -> None:
    old = create(client)
    new = create(client)
    client.patch(
        f"/api/memories/{old['id']}",
        json={"status": "superseded", "superseded_by": new["id"]},
    )

    response = client.patch(f"/api/memories/{old['id']}", json={"status": "active"})

    assert response.status_code == 422