"""Retrieval endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.schemas import RetrievalRequest, RetrievalResult
from app.services import memory_store, retrieval
from app.services.text import tokens

router = APIRouter(prefix="/api/retrieve", tags=["retrieval"])


@router.post("", response_model=RetrievalResult)
def retrieve_memories(
    payload: RetrievalRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> RetrievalResult:
    """Return the memories most relevant to a coding task, with the reason.

    A query made only of stopwords ("the", "and", "is") carries no searchable
    meaning, so it is rejected rather than answered with an arbitrary list.
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

    return retrieval.retrieve(
        memories,
        payload.query,
        limit=payload.limit,
        project=payload.project,
    )