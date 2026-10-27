"""Vector persistence, staleness detection and cascade behaviour."""

import sqlite3

import pytest

from app.schemas import MemoryCategory, MemoryCreate
from app.services import embedding_store, memory_store
from app.services.text import normalize_text

PROVIDER = "local"
MODEL = "test-model"


def make_memory(conn: sqlite3.Connection, content: str = "A memory.") -> str:
    """Create a real memory and return its id.

    Vectors carry a foreign key to memories, so a test cannot invent an id: the
    database would reject it, which is the behaviour we want in production too.
    """
    memory = memory_store.create_memory(
        conn,
        MemoryCreate(
            content=content,
            category=MemoryCategory.DECISION,
            source="test",
            project="payments-api",
        ),
    )
    return memory.id


def test_put_then_get_round_trips_the_vector(conn: sqlite3.Connection) -> None:
    memory_id = make_memory(conn)
    embedding_store.put_vector(
        conn, memory_id, PROVIDER, MODEL, [0.1, 0.2, 0.3], "hash", "2026-01-01"
    )

    stored = embedding_store.get_vectors(conn, PROVIDER, MODEL)

    assert stored[memory_id].vector == [0.1, 0.2, 0.3]


def test_put_replaces_an_existing_vector(conn: sqlite3.Connection) -> None:
    memory_id = make_memory(conn)
    embedding_store.put_vector(conn, memory_id, PROVIDER, MODEL, [1.0], "old", "t1")
    embedding_store.put_vector(conn, memory_id, PROVIDER, MODEL, [2.0], "new", "t2")

    stored = embedding_store.get_vectors(conn, PROVIDER, MODEL)

    assert len(stored) == 1
    assert stored[memory_id].vector == [2.0]
    assert stored[memory_id].content_hash == "new"


def test_vectors_are_scoped_by_provider_and_model(conn: sqlite3.Connection) -> None:
    memory_id = make_memory(conn)
    embedding_store.put_vector(conn, memory_id, "local", "a", [1.0], "h", "t")
    embedding_store.put_vector(conn, memory_id, "hosted", "b", [2.0], "h", "t")

    assert embedding_store.get_vectors(conn, "local", "a")[memory_id].vector == [1.0]
    assert embedding_store.get_vectors(conn, "hosted", "b")[memory_id].vector == [2.0]
    assert embedding_store.get_vectors(conn, "local", "b") == {}


def test_get_can_be_limited_to_specific_memories(conn: sqlite3.Connection) -> None:
    first = make_memory(conn, "First memory.")
    second = make_memory(conn, "Second memory.")
    embedding_store.put_vector(conn, first, PROVIDER, MODEL, [1.0], "h", "t")
    embedding_store.put_vector(conn, second, PROVIDER, MODEL, [2.0], "h", "t")

    stored = embedding_store.get_vectors(conn, PROVIDER, MODEL, [second])

    assert list(stored) == [second]


def test_get_with_an_empty_id_list_returns_nothing(conn: sqlite3.Connection) -> None:
    memory_id = make_memory(conn)
    embedding_store.put_vector(conn, memory_id, PROVIDER, MODEL, [1.0], "h", "t")

    assert embedding_store.get_vectors(conn, PROVIDER, MODEL, []) == {}


def test_content_hash_ignores_punctuation_and_case() -> None:
    assert embedding_store.content_hash("Use request IDs.") == embedding_store.content_hash(
        "use request ids"
    )


def test_content_hash_changes_when_meaning_changes() -> None:
    assert embedding_store.content_hash("Uses PostgreSQL.") != embedding_store.content_hash(
        "Uses MySQL."
    )


def test_deleting_a_memory_deletes_its_vectors(conn: sqlite3.Connection) -> None:
    """Vectors must not outlive the memory they describe."""
    memory_id = make_memory(conn)
    embedding_store.put_vector(conn, memory_id, PROVIDER, MODEL, [1.0], "h", "t")

    memory_store.delete_memory(conn, memory_id)

    assert embedding_store.count_vectors(conn, PROVIDER, MODEL) == 0


def test_count_reports_only_the_matching_provider(conn: sqlite3.Connection) -> None:
    first = make_memory(conn, "First.")
    second = make_memory(conn, "Second.")
    embedding_store.put_vector(conn, first, PROVIDER, MODEL, [1.0], "h", "t")
    embedding_store.put_vector(conn, second, "other", "x", [1.0], "h", "t")

    assert embedding_store.count_vectors(conn, PROVIDER, MODEL) == 1


def test_delete_removes_only_the_matching_provider(conn: sqlite3.Connection) -> None:
    memory_id = make_memory(conn)
    embedding_store.put_vector(conn, memory_id, PROVIDER, MODEL, [1.0], "h", "t")
    embedding_store.put_vector(conn, memory_id, "other", "x", [1.0], "h", "t")

    removed = embedding_store.delete_vectors(conn, PROVIDER, MODEL)

    assert removed == 1
    assert embedding_store.count_vectors(conn, "other", "x") == 1


def test_normalisation_is_the_only_thing_that_changes_the_hash() -> None:
    text = "  We disabled   Redis caching. "
    assert embedding_store.content_hash(text) == embedding_store.content_hash(
        normalize_text(text)
    )
