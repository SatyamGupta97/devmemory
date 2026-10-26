"""Shared test fixtures.

Every test gets its own database file via ``DEVMEMORY_DB_PATH``. That keeps tests
independent without overriding FastAPI dependencies, so the app's real wiring
(config lookup, lifespan, connection handling) is exercised rather than bypassed.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "devmemory.db"
    monkeypatch.setenv("DEVMEMORY_DB_PATH", str(path))
    return path


@pytest.fixture
def client() -> Iterator[TestClient]:
    # The context manager runs the lifespan handler, which creates the schema.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def conn(isolated_database: Path) -> Iterator[sqlite3.Connection]:
    db.init_db(isolated_database)
    connection = db.connect(isolated_database)
    try:
        yield connection
    finally:
        connection.close()
