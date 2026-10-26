"""Bulk import: validation before writing, and all-or-nothing behaviour."""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.schemas import MemoryCategory, MemoryCreate
from app.services import memory_store

SAMPLE_PATH = Path(__file__).resolve().parents[2] / "data" / "sample_memories.json"

ENTRY = {
    "content": "Stripe webhook handlers must be idempotent.",
    "category": "constraint",
    "source": "incident-98",
    "project": "payments-api",
}


def test_import_stores_every_entry(client: TestClient) -> None:
    entries = [
        {**ENTRY, "content": "First imported memory."},
        {**ENTRY, "content": "Second imported memory."},
        {**ENTRY, "content": "Third imported memory."},
    ]

    response = client.post("/api/memories/import", json={"memories": entries})

    assert response.status_code == 201
    body = response.json()
    assert body["imported"] == 3
    assert len(body["ids"]) == 3
    assert len(set(body["ids"])) == 3
    assert len(client.get("/api/memories").json()) == 3


def test_import_returns_readable_records(client: TestClient) -> None:
    response = client.post("/api/memories/import", json={"memories": [ENTRY]})
    memory_id = response.json()["ids"][0]

    stored = client.get(f"/api/memories/{memory_id}").json()

    assert stored["content"] == ENTRY["content"]
    assert stored["status"] == "active"
    assert stored["superseded_by"] is None


def test_import_of_the_sample_dataset_works(client: TestClient) -> None:
    entries = json.loads(SAMPLE_PATH.read_text())

    response = client.post("/api/memories/import", json={"memories": entries})

    assert response.status_code == 201
    assert response.json()["imported"] == len(entries)


def test_one_invalid_entry_rejects_the_whole_import(client: TestClient) -> None:
    entries = [
        {**ENTRY, "content": "Valid first entry."},
        {**ENTRY, "content": "", "category": "decision"},
        {**ENTRY, "content": "Valid third entry."},
    ]

    response = client.post("/api/memories/import", json={"memories": entries})

    assert response.status_code == 422
    # Nothing was written: a half-imported file is worse than a rejected one.
    assert client.get("/api/memories").json() == []


def test_error_points_at_the_offending_entry(client: TestClient) -> None:
    entries = [{**ENTRY}, {**ENTRY, "category": "vibes"}]

    response = client.post("/api/memories/import", json={"memories": entries})

    assert response.status_code == 422
    assert ["body", "memories", 1, "category"] in [
        item["loc"] for item in response.json()["detail"]
    ]


def test_empty_import_is_rejected(client: TestClient) -> None:
    response = client.post("/api/memories/import", json={"memories": []})

    assert response.status_code == 422


def test_import_over_the_batch_limit_is_rejected(client: TestClient) -> None:
    entries = [{**ENTRY, "content": f"Memory number {index}."} for index in range(501)]

    response = client.post("/api/memories/import", json={"memories": entries})

    assert response.status_code == 422
    assert client.get("/api/memories").json() == []


def test_missing_memories_key_is_rejected(client: TestClient) -> None:
    response = client.post("/api/memories/import", json={"items": [ENTRY]})

    assert response.status_code == 422


# --- transaction behaviour, below the HTTP layer ---------------------------


def make_payload(content: str) -> MemoryCreate:
    return MemoryCreate(
        content=content,
        category=MemoryCategory.CONSTRAINT,
        source="test",
        project="payments-api",
    )


def test_import_rolls_back_when_a_write_fails_mid_batch(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database error part-way through must leave zero rows behind.

    Forcing a duplicate id is the simplest realistic mid-batch failure: the first
    insert succeeds, the second violates the primary key.
    """
    duplicate_ids = iter(["duplicate", "duplicate"])
    monkeypatch.setattr(memory_store, "uuid4", lambda: next(duplicate_ids))

    with pytest.raises(sqlite3.IntegrityError):
        memory_store.import_memories(
            conn, [make_payload("First entry."), make_payload("Second entry.")]
        )

    assert memory_store.list_memories(conn) == []


def test_import_shares_one_timestamp_across_the_batch(
    conn: sqlite3.Connection,
) -> None:
    created = memory_store.import_memories(
        conn, [make_payload("First entry."), make_payload("Second entry.")]
    )

    assert created[0].created_at == created[1].created_at


def test_import_preserves_input_order(conn: sqlite3.Connection) -> None:
    created = memory_store.import_memories(
        conn,
        [make_payload(f"Entry {index}.") for index in range(5)],
    )

    assert [memory.content for memory in created] == [
        f"Entry {index}." for index in range(5)
    ]