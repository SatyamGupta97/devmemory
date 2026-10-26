"""Health check endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, Query

from app.db import get_db
from app.schemas import HealthReport
from app.services import health, memory_store

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthReport)
def run_health_check(
    project: str | None = Query(default=None, description="Limit the analysis to one project"),
    conn: sqlite3.Connection = Depends(get_db),
) -> HealthReport:
    """Analyse the stored memories and report quality problems.

    Read-only. This endpoint never modifies, deletes or rewrites a memory: it
    returns findings for a human to act on.

    ``GET`` is used rather than ``POST`` because running the check changes
    nothing, and a repeatable read is easier to cache, bookmark and script
    against.
    """
    memories = memory_store.list_memories(conn, project=project)
    return health.analyze(memories)
