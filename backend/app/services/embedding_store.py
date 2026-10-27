"""Persistence for memory vectors.

Vectors are stored as JSON text. At this scale — hundreds of memories, a few
hundred dimensions — parsing them per query costs microseconds, and avoiding a
binary format keeps the database inspectable with ``sqlite3``. A system with
millions of memories would use a vector index instead; that is a different
problem, and pretending otherwise would add machinery this project cannot yet
justify.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from app.services.text import normalize_text


def content_hash(content: str) -> str:
    """Fingerprint of the text a vector was built from.

    Normalised first, so a change that only affects punctuation or casing — which
    cannot change an embedding meaningfully — does not trigger re-indexing.
    """
    return hashlib.sha256(normalize_text(content).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StoredVector:
    memory_id: str
    vector: list[float]
    content_hash: str


def put_vector(
    conn: sqlite3.Connection,
    memory_id: str,
    provider: str,
    model: str,
    vector: list[float],
    content_hash_value: str,
    embedded_at: str,
) -> None:
    """Insert or replace one vector."""
    conn.execute(
        """
        INSERT INTO memory_embeddings
            (memory_id, provider, model, dimensions, vector, content_hash, embedded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (memory_id, provider, model) DO UPDATE SET
            dimensions = excluded.dimensions,
            vector = excluded.vector,
            content_hash = excluded.content_hash,
            embedded_at = excluded.embedded_at
        """,
        (
            memory_id,
            provider,
            model,
            len(vector),
            json.dumps([round(value, 6) for value in vector]),
            content_hash_value,
            embedded_at,
        ),
    )


def get_vectors(
    conn: sqlite3.Connection,
    provider: str,
    model: str,
    memory_ids: list[str] | None = None,
) -> dict[str, StoredVector]:
    """Fetch vectors for a provider, optionally limited to specific memories."""
    if memory_ids is not None and not memory_ids:
        return {}

    sql = (
        "SELECT memory_id, vector, content_hash FROM memory_embeddings "
        "WHERE provider = ? AND model = ?"
    )
    params: list[object] = [provider, model]

    if memory_ids is not None:
        placeholders = ", ".join("?" for _ in memory_ids)
        sql += f" AND memory_id IN ({placeholders})"
        params.extend(memory_ids)

    rows = conn.execute(sql, params).fetchall()

    result: dict[str, StoredVector] = {}
    for row in rows:
        result[row["memory_id"]] = StoredVector(
            memory_id=row["memory_id"],
            vector=json.loads(row["vector"]),
            content_hash=row["content_hash"],
        )
    return result


def count_vectors(conn: sqlite3.Connection, provider: str, model: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM memory_embeddings WHERE provider = ? AND model = ?",
        (provider, model),
    ).fetchone()
    return int(row["n"]) if row else 0


def delete_vectors(conn: sqlite3.Connection, provider: str, model: str) -> int:
    cursor = conn.execute(
        "DELETE FROM memory_embeddings WHERE provider = ? AND model = ?",
        (provider, model),
    )
    conn.commit()
    return cursor.rowcount