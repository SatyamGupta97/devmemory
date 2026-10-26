"""Persistence across an application restart.

The unit-level reopen test lives in test_memory_store.py. This one goes through
HTTP twice, so it also proves the schema is created on startup and that data
written by one server process is visible to the next.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

MEMORY = {
    "content": "Stripe webhook handlers must be idempotent.",
    "category": "constraint",
    "source": "incident-98",
    "project": "payments-api",
}


def test_memory_written_before_restart_is_readable_after(
    isolated_database: Path,
) -> None:
    with TestClient(app) as first_run:
        created = first_run.post("/api/memories", json=MEMORY).json()

    # A second TestClient is a fresh application lifespan: startup runs again,
    # the schema is re-created if missing, and nothing is cached in memory.
    with TestClient(app) as second_run:
        memories = second_run.get("/api/memories").json()

    assert [memory["id"] for memory in memories] == [created["id"]]
    assert memories[0]["content"] == MEMORY["content"]
    assert isolated_database.exists()
