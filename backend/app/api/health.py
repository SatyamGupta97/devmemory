"""Health check endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_db
from app.schemas import AiAnalysisReport, AiAnalysisRequest, AiStatus, HealthReport
from app.services import ai_inspector, health, llm, memory_store

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


@router.get("/ai/status", response_model=AiStatus)
def ai_status() -> AiStatus:
    """Whether AI-assisted analysis is configured, before the user tries it."""
    configured = llm.is_configured()
    return AiStatus(
        available=configured,
        provider="hosted" if configured else "none",
        model=llm.llm_model() if configured else "",
        reason=None if configured else llm.unavailable_reason(),
    )


@router.post("/ai", response_model=AiAnalysisReport)
def ai_analysis(
    payload: AiAnalysisRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> AiAnalysisReport:
    """Ask a language model for meaning-based findings.

    409 means AI analysis is not configured. The deterministic check at
    ``GET /api/health`` keeps working in that case: the product never depends on
    a model being reachable.
    """
    try:
        client = llm.get_client()
    except llm.LLMNotConfigured as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    memories = memory_store.list_memories(conn, project=payload.project)

    if not memories:
        raise HTTPException(
            status_code=422,
            detail="There are no memories to analyse in this scope.",
        )

    try:
        return ai_inspector.analyze(memories, client, project=payload.project)
    except llm.LLMError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
