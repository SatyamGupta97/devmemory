"""Retrieval endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.schemas import RetrievalRequest, RetrievalResult, RetrievalStrategy
from app.services import embedding_store, memory_store, retrieval
from app.services.embeddings import EmbeddingError, get_provider
from app.services.text import tokens

router = APIRouter(prefix="/api/retrieve", tags=["retrieval"])


@router.post("", response_model=RetrievalResult)
def retrieve_memories(
    payload: RetrievalRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> RetrievalResult:
    """Return the memories most relevant to a coding task, with the reason.

    Two strategies are available and named in the response. The caller always
    knows which one ran, because a ranking means nothing without it.
    """
    if not tokens(payload.query):
        raise HTTPException(
            status_code=422,
            detail=(
                "The query contains no searchable terms. Use words that describe "
                "the task, for example 'add caching to the user service'."
            ),
        )

    memories = memory_store.list_memories(conn, project=payload.project)

    if payload.strategy is RetrievalStrategy.KEYWORD:
        return retrieval.retrieve(
            memories,
            payload.query,
            limit=payload.limit,
            project=payload.project,
        )

    return _retrieve_semantic(conn, memories, payload)


def _retrieve_semantic(
    conn: sqlite3.Connection,
    memories: list,
    payload: RetrievalRequest,
) -> RetrievalResult:
    try:
        provider = get_provider()
    except EmbeddingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    stored = embedding_store.get_vectors(
        conn, provider.name, provider.model, [memory.id for memory in memories]
    )

    if not stored:
        # Answering with an empty list would look like "nothing matched" when the
        # truth is "the index was never built". Say so, with the fix.
        raise HTTPException(
            status_code=409,
            detail=(
                "No embeddings are indexed for this scope, so semantic retrieval "
                "cannot run. Call POST /api/embeddings/index first, or use "
                "strategy=keyword."
            ),
        )

    try:
        query_vector = provider.embed([payload.query])[0]
    except EmbeddingError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return retrieval.retrieve_semantic(
        memories,
        payload.query,
        {memory_id: item.vector for memory_id, item in stored.items()},
        query_vector,
        limit=payload.limit,
        project=payload.project,
        provider=provider.name,
        model=provider.model,
        captures_meaning=provider.captures_meaning,
    )