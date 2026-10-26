"""Memory endpoints.

Handlers stay thin: validate input, call the service, return the result. Anything
that could be reused outside HTTP lives in ``app.services``.
"""

import sqlite3

from fastapi import APIRouter, Depends

from app.db import get_db
from app.schemas import Memory, MemoryCreate
from app.services import memory_store

router = APIRouter(prefix="/api/memories", tags=["memories"])


@router.post("", response_model=Memory, status_code=201)
def create_memory(
    payload: MemoryCreate,
    conn: sqlite3.Connection = Depends(get_db),
) -> Memory:
    """Add a single memory."""
    return memory_store.create_memory(conn, payload)


@router.get("", response_model=list[Memory])
def list_memories(
    conn: sqlite3.Connection = Depends(get_db),
) -> list[Memory]:
    """List every stored memory, newest first."""
    return memory_store.list_memories(conn)
