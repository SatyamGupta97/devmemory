"""Building and refreshing the vector index.

Indexing is explicit rather than automatic on write. Two reasons:

* an embedding call can be slow or cost money, and a memory write should not
  fail because a provider is down;
* the user should know when vectors exist, because retrieval quality depends on
  it and a stale index is worse than a missing one.

Re-indexing is incremental: only memories with no vector, or whose content has
changed since the vector was built, are sent to the provider.
"""

from __future__ import annotations

import sqlite3

from app.schemas import IndexResult, Memory
from app.services import embedding_store
from app.services.embeddings import EmbeddingProvider
from app.services.memory_store import utcnow_iso


def index_memories(
    conn: sqlite3.Connection,
    memories: list[Memory],
    provider: EmbeddingProvider,
    force: bool = False,
) -> IndexResult:
    """Embed every memory that needs it. Never touches the memories themselves."""
    if not memories:
        return IndexResult(
            provider=provider.name,
            model=provider.model,
            dimensions=provider.dimensions,
            captures_meaning=provider.captures_meaning,
            total=0,
            indexed=0,
            skipped=0,
            failed=0,
            errors=[],
        )

    existing = embedding_store.get_vectors(
        conn, provider.name, provider.model, [memory.id for memory in memories]
    )

    pending: list[Memory] = []
    skipped = 0
    for memory in memories:
        stored = existing.get(memory.id)
        if (
            not force
            and stored is not None
            and stored.content_hash == embedding_store.content_hash(memory.content)
        ):
            skipped += 1
            continue
        pending.append(memory)

    if not pending:
        return IndexResult(
            provider=provider.name,
            model=provider.model,
            dimensions=provider.dimensions,
            captures_meaning=provider.captures_meaning,
            total=len(memories),
            indexed=0,
            skipped=skipped,
            failed=0,
            errors=[],
        )

    embedded_at = utcnow_iso()
    errors: list[str] = []

    try:
        vectors = provider.embed([memory.content for memory in pending])
    except Exception as error:  # noqa: BLE001 - report, do not crash the request
        # A provider outage must not lose the vectors that already exist, so the
        # failure is reported per run rather than rolling anything back.
        return IndexResult(
            provider=provider.name,
            model=provider.model,
            dimensions=provider.dimensions,
            captures_meaning=provider.captures_meaning,
            total=len(memories),
            indexed=0,
            skipped=skipped,
            failed=len(pending),
            errors=[str(error)],
        )

    if len(vectors) != len(pending):
        return IndexResult(
            provider=provider.name,
            model=provider.model,
            dimensions=provider.dimensions,
            captures_meaning=provider.captures_meaning,
            total=len(memories),
            indexed=0,
            skipped=skipped,
            failed=len(pending),
            errors=["Provider returned a different number of vectors than texts"],
        )

    with conn:
        for memory, vector in zip(pending, vectors):
            embedding_store.put_vector(
                conn,
                memory.id,
                provider.name,
                provider.model,
                vector,
                embedding_store.content_hash(memory.content),
                embedded_at,
            )

    return IndexResult(
        provider=provider.name,
        model=provider.model,
        dimensions=provider.dimensions,
        captures_meaning=provider.captures_meaning,
        total=len(memories),
        indexed=len(pending),
        skipped=skipped,
        failed=len(errors),
        errors=errors,
    )


def stale_count(
    conn: sqlite3.Connection,
    memories: list[Memory],
    provider: EmbeddingProvider,
) -> int:
    """Memories with no vector, or whose content changed since it was built."""
    existing = embedding_store.get_vectors(
        conn, provider.name, provider.model, [memory.id for memory in memories]
    )
    stale = 0
    for memory in memories:
        stored = existing.get(memory.id)
        if stored is None or stored.content_hash != embedding_store.content_hash(
            memory.content
        ):
            stale += 1
    return stale