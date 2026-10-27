"""Embedding index endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.schemas import EmbeddingStatus, IndexRequest, IndexResult
from app.services import embedding_store, indexing, memory_store
from app.services.embeddings import EmbeddingError, get_provider

router = APIRouter(prefix="/api/embeddings", tags=["embeddings"])


def _provider():
    """Resolve the configured provider, turning a misconfiguration into a 409.

    A wrong provider setting is a server state problem the caller can fix, not a
    bad request, so it is not a 422.
    """
    try:
        return get_provider()
    except EmbeddingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/status", response_model=EmbeddingStatus)
def embedding_status(conn: sqlite3.Connection = Depends(get_db)) -> EmbeddingStatus:
    """Which provider is active, and how much of the collection is indexed.

    Exposed because retrieval quality depends on it: a user must be able to see
    whether they are searching real embeddings or a surface-form fallback, and
    whether the index is stale.
    """
    provider = _provider()
    memories = memory_store.list_memories(conn)

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


@router.post("/index", response_model=IndexResult)
def index_embeddings(
    payload: IndexRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> IndexResult:
    """Build or refresh vectors for the memories in scope.

    Incremental by default: memories whose content has not changed since their
    vector was built are skipped. ``force`` re-embeds everything, which is what
    you want after changing provider or model.
    """
    provider = _provider()
    memories = memory_store.list_memories(conn, project=payload.project)

    try:
        return indexing.index_memories(
            conn, memories, provider, force=payload.force
        )
    except EmbeddingError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error