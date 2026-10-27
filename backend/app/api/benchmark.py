"""Benchmark endpoints.

The same benchmark file is run against whichever strategy the caller names, so a
comparison is always like-for-like: identical queries, identical ground truth,
identical cut-off.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.schemas import (
    BenchmarkDefinition,
    BenchmarkReport,
    BenchmarkRunRequest,
    RetrievalStrategy,
)
from app.services import benchmark, embedding_store, memory_store, retrieval
from app.services.embeddings import EmbeddingError, get_provider

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


@router.get("", response_model=BenchmarkDefinition)
def get_benchmark() -> BenchmarkDefinition:
    """Return the version-controlled benchmark, so a client can show the cases."""
    try:
        return benchmark.load_definition()
    except benchmark.BenchmarkError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/run", response_model=BenchmarkReport)
def run_benchmark(
    payload: BenchmarkRunRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> BenchmarkReport:
    """Score a strategy against the benchmark and return per-query results."""
    try:
        definition = benchmark.load_definition()
    except benchmark.BenchmarkError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    if payload.strategy is RetrievalStrategy.KEYWORD:
        def rank(query: str, project: str | None, k: int) -> list[str]:
            pool = memory_store.list_memories(
                conn, project=payload.project or project
            )
            result = retrieval.retrieve(pool, query, limit=k, project=project)
            return [match.memory.id for match in result.matches]

        return benchmark.run(
            definition,
            memory_store.list_memories(conn, project=payload.project),
            rank,
            strategy="keyword-bm25",
            k=payload.k,
        )

    return _run_semantic(conn, definition, payload)


def _run_semantic(
    conn: sqlite3.Connection,
    definition,
    payload: BenchmarkRunRequest,
) -> BenchmarkReport:
    try:
        provider = get_provider()
    except EmbeddingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    memories = memory_store.list_memories(conn, project=payload.project)
    stored = embedding_store.get_vectors(
        conn, provider.name, provider.model, [memory.id for memory in memories]
    )

    if not stored:
        raise HTTPException(
            status_code=409,
            detail=(
                "No embeddings are indexed, so the semantic strategy cannot be "
                "benchmarked. Call POST /api/embeddings/index first."
            ),
        )

    def rank(query: str, project: str | None, k: int) -> list[str]:
        scoped = [
            memory
            for memory in memories
            if project is None or memory.project == project
        ]
        vectors = {
            memory.id: stored[memory.id].vector
            for memory in scoped
            if memory.id in stored
        }
        if not vectors:
            return []

        try:
            query_vector = provider.embed([query])[0]
        except EmbeddingError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

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
        definition, memories, rank, strategy="semantic-embedding", k=payload.k
    )