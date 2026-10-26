"""Service-layer tests: storage behaviour, independent of HTTP."""

import sqlite3
import uuid
from pathlib import Path

import pytest

from app import db
from app.schemas import MemoryCategory, MemoryCreate, MemoryStatus
from app.services import memory_store


def make_payload(**overrides: object) -> MemoryCreate:
    defaults: dict[str, object] = {
        "content": "The user service uses PostgreSQL 15 for persistence.",
        "category": MemoryCategory.DECISION,
        "source": "architecture-review",
        "project": "payments-api",
    }
    return MemoryCreate(**{**defaults, **overrides})


def test_create_memory_assigns_id_and_timestamps(conn: sqlite3.Connection) -> None:
    memory = memory_store.create_memory(conn, make_payload())

    assert uuid.UUID(memory.id)  # parses, so it is a real UUID
    assert memory.created_at == memory.updated_at
    assert memory.created_at.tzinfo is not None
    assert memory.status is MemoryStatus.ACTIVE
    assert memory.superseded_by is None


def test_create_memory_persists_the_given_fields(conn: sqlite3.Connection) -> None:
    memory = memory_store.create_memory(
        conn, make_payload(confidence=0.75, project="analytics")
    )

    assert memory.content == "The user service uses PostgreSQL 15 for persistence."
    assert memory.category is MemoryCategory.DECISION
    assert memory.project == "analytics"
    assert memory.confidence == 0.75


def test_confidence_is_optional(conn: sqlite3.Connection) -> None:
    memory = memory_store.create_memory(conn, make_payload())

    assert memory.confidence is None


def test_list_memories_is_newest_first_and_deterministic(
    conn: sqlite3.Connection,
) -> None:
    first = memory_store.create_memory(conn, make_payload(content="First memory."))
    second = memory_store.create_memory(conn, make_payload(content="Second memory."))

    listed = memory_store.list_memories(conn)
    assert [memory.id for memory in listed] == [second.id, first.id]

    # Same query twice must produce the same order.
    assert [m.id for m in memory_store.list_memories(conn)] == [m.id for m in listed]


def test_list_memories_is_empty_initially(conn: sqlite3.Connection) -> None:
    assert memory_store.list_memories(conn) == []


def test_memories_with_identical_timestamps_keep_insertion_order(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: same-second writes must not come back in random order.

    Freezing the clock removes the microsecond difference that would otherwise
    hide a tie, so the tiebreaker itself is what is being tested.
    """
    monkeypatch.setattr(memory_store, "utcnow_iso", lambda: "2026-01-01T00:00:00+00:00")

    first = memory_store.create_memory(conn, make_payload(content="First memory."))
    second = memory_store.create_memory(conn, make_payload(content="Second memory."))

    listed = memory_store.list_memories(conn)

    assert [memory.id for memory in listed] == [second.id, first.id]


def test_memories_survive_reopening_the_database(
    isolated_database: Path, conn: sqlite3.Connection
) -> None:
    created = memory_store.create_memory(conn, make_payload())
    conn.close()

    # Simulate a restart: brand new connection, no in-memory state carried over.
    reopened = db.connect()
    try:
        memories = memory_store.list_memories(reopened)
    finally:
        reopened.close()

    assert [memory.id for memory in memories] == [created.id]
    assert memories[0].content == created.content


def test_database_rejects_blank_content(conn: sqlite3.Connection) -> None:
    """Defence in depth: the CHECK constraint holds even if validation is bypassed."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO memories
                (id, content, category, source, project,
                 created_at, updated_at, status)
            VALUES ('x', '   ', 'fact', 'test', 'proj', '2026-01-01', '2026-01-01', 'active')
            """
        )
