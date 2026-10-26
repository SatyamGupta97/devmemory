"""SQLite connection handling and schema definition.

Why raw ``sqlite3`` instead of SQLAlchemy: the schema is one table and every
query is a handful of lines. An ORM would add a dependency, a session lifecycle
and a second way to describe the same columns, without removing any real work
yet. We can revisit if queries start composing.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

from app.config import get_db_path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id            TEXT PRIMARY KEY,
    content       TEXT NOT NULL CHECK (length(trim(content)) > 0),
    category      TEXT NOT NULL,
    source        TEXT NOT NULL,
    project       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    confidence    REAL CHECK (
                      confidence IS NULL
                      OR (confidence >= 0.0 AND confidence <= 1.0)
                  ),
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'superseded')),
    superseded_by TEXT REFERENCES memories(id)
);

CREATE INDEX IF NOT EXISTS idx_memories_project
    ON memories (project);

CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories (created_at);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with the pragmas this app depends on.

    ``row_factory = sqlite3.Row`` lets callers read columns by name, which keeps
    the row -> Pydantic conversion honest when the schema grows.
    """
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets reads proceed while a write is in flight. Harmless at this scale
    # and avoids "database is locked" surprises once the UI polls.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create the schema if it is missing. Safe to call on every startup."""
    with closing(connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, always closed."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
