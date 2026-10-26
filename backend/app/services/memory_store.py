"""Memory persistence operations.

Kept separate from the HTTP layer so the same functions can be called by tests,
by a future CLI, and by the import endpoint in Phase 2 — without going through
HTTP.
"""

import sqlite3
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from app.schemas import Memory, MemoryCategory, MemoryCreate, MemoryStatus, MemoryUpdate

# Columns a client may change after creation. Anything else is server-owned.
UPDATABLE_FIELDS = frozenset(
    {"content", "category", "source", "project", "confidence", "status", "superseded_by"}
)


class MemoryRuleViolation(ValueError):
    """The requested change is well-formed but not allowed.

    API layer maps this to HTTP 422: the body parsed fine, but it conflicts with
    a rule about the stored data (e.g. superseding an unknown memory).
    """


class MemoryConflictError(RuntimeError):
    """The change would break an existing reference between memories.

    API layer maps this to HTTP 409. Deleting a memory that another memory names
    as its replacement is a conflict, not a server fault, and not something we
    silently resolve: clearing the other memory's history without being asked
    would violate the product promise that decisions are never rewritten
    automatically.
    """


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


def _created_at(payload: MemoryCreate, fallback: str) -> str:
    """Use the caller-supplied original timestamp when there is one.

    Imported memories often carry the date they were originally captured.
    Keeping that date is what makes "this memory might be stale" a question the
    tool can answer.
    """
    if payload.created_at is None:
        return fallback
    created = payload.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(timezone.utc).isoformat()


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
            _created_at(payload, now),
            now,
            payload.confidence,
        ),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row is None:  # pragma: no cover - would mean the insert vanished
        raise RuntimeError(f"memory {memory_id} not found immediately after insert")
    return _row_to_memory(row)


def list_memories(
    conn: sqlite3.Connection,
    project: str | None = None,
    category: MemoryCategory | None = None,
) -> list[Memory]:
    """Newest first, tiebroken by insertion order.

    ``rowid DESC`` is SQLite's insertion sequence. Ordering by it rather than by
    ``id`` means two memories created in the same microsecond still come back in
    the order they were written, and a clock adjustment cannot reorder history.
    Deterministic ordering matters: an unstable list order would make retrieval
    and benchmark results unreproducible later.
    """
    clauses: list[str] = []
    params: list[object] = []

    if project is not None:
        clauses.append("project = ?")
        params.append(project)
    if category is not None:
        clauses.append("category = ?")
        params.append(category.value)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM memories{where} ORDER BY created_at DESC, rowid DESC",
        params,
    ).fetchall()
    return [_row_to_memory(row) for row in rows]


def get_memory(conn: sqlite3.Connection, memory_id: str) -> Memory | None:
    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return None if row is None else _row_to_memory(row)


def update_memory(
    conn: sqlite3.Connection, memory_id: str, payload: MemoryUpdate
) -> Memory | None:
    """Apply a partial update. Returns None if the memory does not exist.

    The supersede invariant is enforced here rather than only in the API, so any
    caller (future CLI, change-suggestion approval flow) gets the same rules.
    """
    current = get_memory(conn, memory_id)
    if current is None:
        return None

    changes: dict[str, object] = {}
    for field in sorted(payload.model_fields_set & UPDATABLE_FIELDS):
        value = getattr(payload, field)
        if isinstance(value, Enum):
            value = value.value
        changes[field] = value

    if not changes:  # pragma: no cover - MemoryUpdate already requires a field
        return current

    target_status = str(changes.get("status", current.status.value))
    target_replacement = (
        changes["superseded_by"]
        if "superseded_by" in changes
        else current.superseded_by
    )

    if target_replacement is not None:
        if target_replacement == memory_id:
            raise MemoryRuleViolation("a memory cannot supersede itself")
        if target_status != MemoryStatus.SUPERSEDED.value:
            raise MemoryRuleViolation(
                "status must be 'superseded' when superseded_by is set"
            )
        exists = conn.execute(
            "SELECT 1 FROM memories WHERE id = ?", (target_replacement,)
        ).fetchone()
        if exists is None:
            raise MemoryRuleViolation(
                f"superseded_by references unknown memory '{target_replacement}'"
            )

    changes["updated_at"] = utcnow_iso()

    # Field names come from UPDATABLE_FIELDS, never from raw user input, so
    # interpolating them into the statement is safe. Values stay parameterised.
    assignments = ", ".join(f"{column} = ?" for column in changes)
    conn.execute(
        f"UPDATE memories SET {assignments} WHERE id = ?",
        (*changes.values(), memory_id),
    )
    conn.commit()

    updated = get_memory(conn, memory_id)
    if updated is None:  # pragma: no cover - row cannot vanish mid-transaction
        raise RuntimeError(f"memory {memory_id} disappeared during update")
    return updated


def delete_memory(conn: sqlite3.Connection, memory_id: str) -> bool:
    """Delete a memory. Returns False when it did not exist.

    Refuses to delete a memory that others name as their replacement. The check
    is explicit so the error can say *which* memories would be left dangling;
    the foreign key constraint remains as a backstop.
    """
    referrers = conn.execute(
        "SELECT id FROM memories WHERE superseded_by = ? ORDER BY created_at, id",
        (memory_id,),
    ).fetchall()

    if referrers:
        referrer_ids = ", ".join(row["id"] for row in referrers)
        raise MemoryConflictError(
            f"Memory '{memory_id}' is named as the replacement by "
            f"{len(referrers)} other memory/memories ({referrer_ids}). "
            "Clear that reference before deleting it."
        )

    try:
        cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise MemoryConflictError(
            f"Memory '{memory_id}' is still referenced by another memory."
        ) from exc

    conn.commit()
    return cursor.rowcount > 0


def import_memories(
    conn: sqlite3.Connection, payloads: list[MemoryCreate]
) -> list[Memory]:
    """Insert many memories as one all-or-nothing transaction.

    A partially imported file is worse than a rejected one: the user cannot tell
    which rows landed, and re-importing creates duplicates. Validation happens
    before this call, so the transaction is a second line of defence against a
    mid-batch database error.
    """
    now = utcnow_iso()
    created_ids: list[str] = []

    with conn:  # commit on success, rollback if anything raises
        for payload in payloads:
            memory_id = str(uuid4())
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
                    _created_at(payload, now),
                    now,
                    payload.confidence,
                ),
            )
            created_ids.append(memory_id)

    # MemoryImportRequest caps the batch at 500, below SQLite's 999 bound
    # parameter limit, so a single IN (...) lookup is safe.
    placeholders = ", ".join("?" for _ in created_ids)
    rows = conn.execute(
        f"SELECT * FROM memories WHERE id IN ({placeholders})", created_ids
    ).fetchall()
    by_id = {row["id"]: _row_to_memory(row) for row in rows}
    return [by_id[memory_id] for memory_id in created_ids]
