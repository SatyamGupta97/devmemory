"""Consolidated report endpoints.

The only endpoint that composes the other features. It re-uses their services
rather than recomputing anything, so a number in the report always matches the
number on the endpoint it came from.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.db import get_db
from app.schemas import InspectorReport, RetrievalStrategy
from app.services import (
    benchmark,
    embedding_store,
    health,
    llm,
    memory_store,
    report,
    report_export,
    retrieval,
)
from app.services.embeddings import EmbeddingError, get_provider

router = APIRouter(prefix="/api/report", tags=["report"])


def _keyword_rank(conn: sqlite3.Connection, memories, scope: str | None):
    def rank(query: str, project: str | None, k: int) -> list[str]:
        pool = memory_store.list_memories(conn, project=scope or project)
        result = retrieval.retrieve(pool, query, limit=k, project=project)
        return [match.memory.id for match in result.matches]

    return rank


def build_report(
    conn: sqlite3.Connection,
    scope: str | None,
    include_semantic: bool = True,
) -> InspectorReport:
    """Assemble the report from the live services."""
    memories = memory_store.list_memories(conn, project=scope)

    try:
        definition = benchmark.load_definition()
    except benchmark.BenchmarkError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    keyword_report = benchmark.run(
        definition,
        memories,
        _keyword_rank(conn, memories, scope),
        strategy="keyword-bm25",
    )

    # Embedding status is always reported; if the provider cannot even be built
    # the report still describes the collection.
    try:
        provider = get_provider()
        embedding_status = _embedding_status(conn, provider, memories)
    except EmbeddingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    semantic_report = None
    if include_semantic and embedding_status.indexed_memories:
        semantic_report = _semantic_benchmark(
            conn, definition, memories, scope, provider
        )

    ai_report = None
    ai_reason = llm.unavailable_reason()
    if llm.is_configured() and memories:
        # A model failure must not destroy the report: the deterministic half is
        # the product, and the AI half is an optional extra.
        try:
            from app.services import ai_inspector

            ai_report = ai_inspector.analyze(memories, llm.get_client())
        except llm.LLMError as error:
            ai_reason = f"AI analysis failed: {error}"
    elif not memories:
        ai_reason = "There are no memories to analyse."

    return report.build(
        memories,
        health.analyze(memories),
        keyword_report,
        embedding_status,
        ai_report,
        ai_reason,
        benchmark_version=definition.version,
        benchmark_query_count=len(definition.queries),
        semantic=semantic_report,
        scope_project=scope,
    )


def _embedding_status(conn, provider, memories):
    from app.schemas import EmbeddingStatus
    from app.services import indexing

    return EmbeddingStatus(
        provider=provider.name,
        model=provider.model,
        dimensions=provider.dimensions,
        captures_meaning=provider.captures_meaning,
        description=provider.description,
        total_memories=len(memories),
        indexed_memories=embedding_store.count_vectors(
            conn, provider.name, provider.model
        ),
        stale_memories=indexing.stale_count(conn, memories, provider),
    )


def _semantic_benchmark(conn, definition, memories, scope, provider):
    stored = embedding_store.get_vectors(
        conn, provider.name, provider.model, [memory.id for memory in memories]
    )
    if not stored:
        return None

    def rank(query: str, project: str | None, k: int) -> list[str]:
        scoped = [
            memory for memory in memories if project is None or memory.project == project
        ]
        vectors = {
            memory.id: stored[memory.id].vector
            for memory in scoped
            if memory.id in stored
        }
        if not vectors:
            return []
        query_vector = provider.embed([query])[0]
        result = retrieval.retrieve_semantic(
            scoped,
            query,
            vectors,
            query_vector,
            limit=k,
            provider=provider.name,
            model=provider.model,
            captures_meaning=provider.captures_meaning,
        )
        return [match.memory.id for match in result.matches]

    return benchmark.run(
        definition, memories, rank, strategy="semantic-embedding"
    )


@router.get("", response_model=InspectorReport)
def get_report(
    project: str | None = Query(default=None, max_length=100),
    conn: sqlite3.Connection = Depends(get_db),
) -> InspectorReport:
    """Everything DevMemory knows about this collection, in one document."""
    return build_report(conn, project)


@router.get("/export")
def export_report(
    project: str | None = Query(default=None, max_length=100),
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    """Download the same report as Markdown or JSON.

    Both formats are rendered from one InspectorReport, so the export cannot
    disagree with the screen.
    """
    document = build_report(conn, project)

    if format == "json":
        return Response(
            content=document.model_dump_json(indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="devmemory-report.json"'
            },
        )

    return Response(
        content=report_export.to_markdown(document),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="devmemory-report.md"'
        },
    )