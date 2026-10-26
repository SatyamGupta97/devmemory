"""Memory endpoints.

Handlers stay thin: validate input, call the service, translate domain errors
into HTTP status codes. Anything reusable outside HTTP lives in ``app.services``.

Status codes used here, and why:
  200  ok
  201  a new resource was created
  204  deleted, nothing left to return
  404  the memory id does not exist
  409  the change would break a link between memories
  422  the body parsed but is invalid, or conflicts with a stored-data rule
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.db import get_db
from app.schemas import (
    Memory,
    MemoryCategory,
    MemoryCreate,
    MemoryImportRequest,
    MemoryImportResult,
    MemoryUpdate,
)
from app.services import memory_store

router = APIRouter(prefix="/api/memories", tags=["memories"])


def _not_found(memory_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")


@router.post("", response_model=Memory, status_code=201)
def create_memory(
    payload: MemoryCreate,
    conn: sqlite3.Connection = Depends(get_db),
) -> Memory:
    """Add a single memory."""
    return memory_store.create_memory(conn, payload)


@router.get("", response_model=list[Memory])
def list_memories(
    project: str | None = Query(default=None, description="Exact project filter"),
    category: MemoryCategory | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[Memory]:
    """List memories, newest first, optionally filtered by project and category."""
    return memory_store.list_memories(conn, project=project, category=category)


# Declared before /{memory_id} so "import" is never parsed as an id.
@router.post("/import", response_model=MemoryImportResult, status_code=201)
def import_memories(
    payload: MemoryImportRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> MemoryImportResult:
    """Import a batch of memories. Either every entry is stored, or none is."""
    created = memory_store.import_memories(conn, payload.memories)
    return MemoryImportResult(
        imported=len(created), ids=[memory.id for memory in created]
    )


@router.get("/{memory_id}", response_model=Memory)
def get_memory(
    memory_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> Memory:
    """Fetch a single memory by id."""
    memory = memory_store.get_memory(conn, memory_id)
    if memory is None:
        raise _not_found(memory_id)
    return memory


@router.patch("/{memory_id}", response_model=Memory)
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    conn: sqlite3.Connection = Depends(get_db),
) -> Memory:
    """Update selected fields of a memory."""
    try:
        memory = memory_store.update_memory(conn, memory_id, payload)
    except memory_store.MemoryRuleViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if memory is None:
        raise _not_found(memory_id)
    return memory


@router.delete("/{memory_id}", status_code=204, response_model=None)
def delete_memory(
    memory_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    """Delete a memory.

    409 means another memory names this one as its replacement, so removing it
    would break a recorded history link. The caller must clear that first.
    """
    try:
        deleted = memory_store.delete_memory(conn, memory_id)
    except memory_store.MemoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not deleted:
        raise _not_found(memory_id)
    return Response(status_code=204)