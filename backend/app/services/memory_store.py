"""Memory persistence operations.

Kept separate from the HTTP layer so the same functions can be called by tests,
by a future CLI, and by the import endpoint in Phase 2 — without going through
HTTP.
"""

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas import Memory, MemoryCreate


def utcnow_iso() -> str:
    """Current UTC time as a sortable ISO 8601 string.

    Stored as text because SQLite has no native datetime type, and ISO 8601 in
    UTC sorts correctly as a plain string. Microsecond precision is kept
    deliberately: with whole-second timestamps, memories added in the same second
    are indistinguishable and "newest first" ordering becomes arbitrary.
    """
    return datetime.now(timezone.utc).isoformat()


def _row_to_memory(row: sqlite3.Row) -> Memory:
    return Memory.model_validate(dict(row))


def create_memory(conn: sqlite3.Connection, payload: MemoryCreate) -> Memory:
    """Insert a memory and return it as stored."""
    memory_id = str(uuid4())
    now = utcnow_iso()

    conn.execute(
        """
        INSERT INTO memories
            (id, content, category, source, project,
             created_at, updated_at, confidence, status, superseded_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL)
        """,
        (
            memory_id,
            payload.content,
            payload.category.value,
            payload.source,
            payload.project,
            now,
            now,
            payload.confidence,
        ),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row is None:  # pragma: no cover - would mean the insert vanished
        raise RuntimeError(f"memory {memory_id} not found immediately after insert")
    return _row_to_memory(row)


def list_memories(conn: sqlite3.Connection) -> list[Memory]:
    """Newest first, tiebroken by insertion order.

    ``rowid DESC`` is SQLite's insertion sequence. Ordering by it rather than by
    ``id`` means two memories created in the same microsecond still come back in
    the order they were written, and a clock adjustment cannot reorder history.
    Deterministic ordering matters: an unstable list order would make retrieval
    and benchmark results unreproducible later.
    """
    rows = conn.execute(
        "SELECT * FROM memories ORDER BY created_at DESC, rowid DESC"
    ).fetchall()
    return [_row_to_memory(row) for row in rows]
