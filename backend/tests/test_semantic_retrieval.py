"""Semantic retrieval and the embedding API."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.schemas import Memory, MemoryCategory
from app.services import embedding_store, retrieval
from app.services.embeddings import LocalHashingProvider, get_provider

PROVIDER = "local"


def make_memory(memory_id: str, content: str, project: str = "payments-api") -> Memory:
    import datetime as dt

    stamp = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    return Memory(
        id=memory_id,
        content=content,
        category=MemoryCategory.DECISION,
        source="test",
        project=project,
        created_at=stamp,
        updated_at=stamp,
        confidence=0.9,
    )


# --- semantic ranking, below HTTP -------------------------------------------


def test_semantic_ranks_by_cosine_similarity() -> None:
    provider = LocalHashingProvider(dimensions=1024)
    memories = [
        make_memory("a", "We disabled Redis caching for user records."),
        make_memory("b", "Never log full card numbers or CVV values."),
    ]
    vectors = {
        memory.id: vector
        for memory, vector in zip(memories, provider.embed([m.content for m in memories]))
    }

    result = retrieval.retrieve_semantic(
        memories,
        "redis caching",
        vectors,
        provider.embed(["redis caching"])[0],
        provider=provider.name,
        model=provider.model,
        captures_meaning=provider.captures_meaning,
    )

    assert [match.memory.id for match in result.matches] == ["a"]
    assert result.matches[0].method == "semantic-embedding"
    assert 0 < result.matches[0].score <= 1


def test_a_memory_without_a_vector_is_excluded_not_scored_zero() -> None:
    """A missing vector means 'unknown', so the memory is left out and reported."""
    provider = LocalHashingProvider(dimensions=1024)
    memories = [
        make_memory("a", "We disabled Redis caching for user records."),
        make_memory("b", "Never log full card numbers."),
    ]
    vectors = {"a": provider.embed(["We disabled Redis caching for user records."])[0]}

    result = retrieval.retrieve_semantic(
        memories,
        "redis caching",
        vectors,
        provider.embed(["redis caching"])[0],
        provider=provider.name,
        model=provider.model,
    )

    assert [match.memory.id for match in result.matches] == ["a"]
    assert result.considered == 1
    assert any("no stored vector" in note for note in result.notes)


def test_zero_similarity_memories_are_not_returned() -> None:
    provider = LocalHashingProvider(dimensions=1024)
    memories = [
        make_memory("a", "kubernetes helm charts"),
        make_memory("b", "card numbers must never be logged"),
    ]
    vectors = {
        memory.id: vector
        for memory, vector in zip(memories, provider.embed([m.content for m in memories]))
    }

    result = retrieval.retrieve_semantic(
        memories,
        "kubernetes helm",
        vectors,
        provider.embed(["kubernetes helm"])[0],
        provider=provider.name,
        model=provider.model,
    )

    assert [match.memory.id for match in result.matches] == ["a"]


def test_semantic_ranking_is_reproducible() -> None:
    provider = LocalHashingProvider(dimensions=1024)
    memories = [
        make_memory("a", "We disabled Redis caching."),
        make_memory("b", "Redis caching was disabled."),
        make_memory("c", "Unrelated text about cards."),
    ]
    vectors = {
        memory.id: vector
        for memory, vector in zip(memories, provider.embed([m.content for m in memories]))
    }
    query_vector = provider.embed(["redis caching"])[0]

    first = retrieval.retrieve_semantic(
        memories, "redis caching", vectors, query_vector, provider="local"
    )
    second = retrieval.retrieve_semantic(
        memories, "redis caching", vectors, query_vector, provider="local"
    )

    assert [m.memory.id for m in first.matches] == [m.memory.id for m in second.matches]
    assert [m.score for m in first.matches] == [m.score for m in second.matches]


def test_semantic_notes_admit_when_the_provider_is_not_semantic() -> None:
    notes = retrieval.semantic_notes(False, "local", "hashed-ngrams-1024")
    joined = " ".join(notes)

    assert "does NOT understand meaning" in joined


def test_semantic_notes_describe_a_hosted_provider_differently() -> None:
    notes = retrieval.semantic_notes(True, "hosted", "text-embedding-3-small")
    joined = " ".join(notes)

    assert "compares meaning rather than words" in joined
    assert "does NOT understand meaning" not in joined


def test_semantic_explanation_says_which_provider_produced_the_score() -> None:
    provider = LocalHashingProvider(dimensions=1024)
    memories = [make_memory("a", "We disabled Redis caching.")]
    vectors = {"a": provider.embed(["We disabled Redis caching."])[0]}

    result = retrieval.retrieve_semantic(
        memories,
        "redis caching",
        vectors,
        provider.embed(["redis caching"])[0],
        provider=provider.name,
        model=provider.model,
        captures_meaning=False,
    )

    explanation = result.matches[0].explanation
    assert "local" in explanation
    assert "surface form" in explanation


# --- embedding API ----------------------------------------------------------


MEMORIES = [
    {
        "content": "We disabled Redis caching for user records because stale cache "
                   "entries caused wrong account balances.",
        "category": "failure",
        "source": "incident-142",
        "project": "payments-api",
    },
    {
        "content": "The user service uses PostgreSQL 15 for persistence.",
        "category": "decision",
        "source": "architecture-review",
        "project": "payments-api",
    },
    {
        "content": "The reporting service uses DuckDB for nightly jobs.",
        "category": "decision",
        "source": "analytics-rfc",
        "project": "analytics",
    },
]


def seed(client: TestClient) -> None:
    assert client.post("/api/memories/import", json={"memories": MEMORIES}).status_code == 201


def test_status_reports_the_active_provider(client: TestClient) -> None:
    seed(client)

    body = client.get("/api/embeddings/status").json()

    assert body["provider"] == "local"
    assert body["captures_meaning"] is False
    assert body["total_memories"] == 3
    assert body["indexed_memories"] == 0
    assert body["stale_memories"] == 3
    assert body["description"]


def test_index_builds_vectors_for_every_memory(client: TestClient) -> None:
    seed(client)

    body = client.post("/api/embeddings/index", json={}).json()

    assert body["indexed"] == 3
    assert body["skipped"] == 0
    assert body["failed"] == 0
    assert body["captures_meaning"] is False
    assert client.get("/api/embeddings/status").json()["indexed_memories"] == 3


def test_indexing_twice_skips_current_vectors(client: TestClient) -> None:
    seed(client)
    client.post("/api/embeddings/index", json={})

    body = client.post("/api/embeddings/index", json={}).json()

    assert body["indexed"] == 0
    assert body["skipped"] == 3


def test_force_re_embeds_everything(client: TestClient) -> None:
    seed(client)
    client.post("/api/embeddings/index", json={})

    body = client.post("/api/embeddings/index", json={"force": True}).json()

    assert body["indexed"] == 3


def test_editing_a_memory_makes_its_vector_stale(client: TestClient) -> None:
    seed(client)
    client.post("/api/embeddings/index", json={})
    memory_id = client.get("/api/memories").json()[0]["id"]

    client.patch(f"/api/memories/{memory_id}", json={"content": "Completely new text."})

    status = client.get("/api/embeddings/status").json()
    assert status["stale_memories"] == 1

    result = client.post("/api/embeddings/index", json={}).json()
    assert result["indexed"] == 1
    assert result["skipped"] == 2


def test_indexing_can_be_scoped_to_a_project(client: TestClient) -> None:
    seed(client)

    body = client.post(
        "/api/embeddings/index", json={"project": "payments-api"}
    ).json()

    assert body["total"] == 2
    assert body["indexed"] == 2
    assert client.get("/api/embeddings/status").json()["indexed_memories"] == 2


def test_indexing_an_empty_collection_is_not_an_error(client: TestClient) -> None:
    body = client.post("/api/embeddings/index", json={}).json()

    assert body["total"] == 0
    assert body["indexed"] == 0


def test_semantic_retrieval_works_once_indexed(client: TestClient) -> None:
    seed(client)
    client.post("/api/embeddings/index", json={})

    body = client.post(
        "/api/retrieve", json={"query": "redis caching", "strategy": "semantic"}
    ).json()

    assert body["strategy"] == "semantic-embedding"
    assert body["matches"][0]["memory"]["content"].startswith("We disabled Redis caching")
    assert body["matches"][0]["method"] == "semantic-embedding"
    assert body["matches"][0]["matched_terms"] == []


def test_semantic_retrieval_without_an_index_explains_itself(
    client: TestClient,
) -> None:
    seed(client)

    response = client.post(
        "/api/retrieve", json={"query": "redis caching", "strategy": "semantic"}
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "POST /api/embeddings/index" in detail
    assert "strategy=keyword" in detail


def test_semantic_retrieval_respects_the_project_filter(client: TestClient) -> None:
    seed(client)
    client.post("/api/embeddings/index", json={})

    body = client.post(
        "/api/retrieve",
        json={"query": "duckdb", "strategy": "semantic", "project": "payments-api"},
    ).json()

    assert body["matches"] == []


def test_keyword_remains_the_default_strategy(client: TestClient) -> None:
    seed(client)

    body = client.post("/api/retrieve", json={"query": "redis caching"}).json()

    assert body["strategy"] == "keyword-bm25"


def test_keyword_and_semantic_can_be_compared_on_the_same_query(
    client: TestClient,
) -> None:
    """The comparison the benchmark will formalise."""
    seed(client)
    client.post("/api/embeddings/index", json={})

    keyword = client.post(
        "/api/retrieve", json={"query": "redis caching", "strategy": "keyword"}
    ).json()
    semantic = client.post(
        "/api/retrieve", json={"query": "redis caching", "strategy": "semantic"}
    ).json()

    assert keyword["strategy"] != semantic["strategy"]
    assert keyword["matches"][0]["memory"]["id"] == semantic["matches"][0]["memory"]["id"]


def test_unknown_strategy_is_rejected(client: TestClient) -> None:
    response = client.post("/api/retrieve", json={"query": "x", "strategy": "magic"})

    assert response.status_code == 422


def test_embeddings_endpoints_are_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/embeddings/status"]
    assert "post" in paths["/api/embeddings/index"]


def test_indexing_does_not_modify_the_memories(client: TestClient) -> None:
    seed(client)
    before = client.get("/api/memories").json()

    client.post("/api/embeddings/index", json={})

    assert client.get("/api/memories").json() == before


def test_stale_vectors_are_not_used_for_retrieval_after_an_edit(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """A vector built from old text must not rank the new text.

    The indexer records a content hash, so retrieval can tell the difference.
    This test asserts the hash changes; the indexer test above asserts the
    re-embed happens.
    """
    seed(client)
    client.post("/api/embeddings/index", json={})
    memory_id = client.get("/api/memories").json()[0]["id"]

    stored = embedding_store.get_vectors(conn, PROVIDER, get_provider().model)[memory_id]
    client.patch(f"/api/memories/{memory_id}", json={"content": "Entirely new content."})
    current = client.get(f"/api/memories/{memory_id}").json()

    assert stored.content_hash != embedding_store.content_hash(current["content"])

def test_similarity_below_the_floor_is_not_returned() -> None:
    """Hashing produces small non-zero scores between unrelated texts."""
    provider = LocalHashingProvider(dimensions=1024)
    memories = [make_memory("b", "Never log full card numbers or CVV values.")]
    vectors = {"b": provider.embed(["Never log full card numbers or CVV values."])[0]}

    result = retrieval.retrieve_semantic(
        memories,
        "redis caching",
        vectors,
        provider.embed(["redis caching"])[0],
        provider=provider.name,
        model=provider.model,
    )

    assert result.matches == []


def test_the_floor_is_documented_in_the_notes() -> None:
    provider = LocalHashingProvider(dimensions=1024)
    memories = [make_memory("a", "We disabled Redis caching.")]
    vectors = {"a": provider.embed(["We disabled Redis caching."])[0]}

    result = retrieval.retrieve_semantic(
        memories,
        "redis caching",
        vectors,
        provider.embed(["redis caching"])[0],
        provider=provider.name,
        model=provider.model,
    )

    assert any("treated as no match" in note for note in result.notes)


def test_the_provider_floor_is_used_when_given() -> None:
    """A meaning-capturing provider's own cut-off must be respected."""
    provider = LocalHashingProvider(dimensions=1024)
    memories = [make_memory("a", "We disabled Redis caching for user records.")]
    vectors = {"a": provider.embed(["We disabled Redis caching for user records."])[0]}
    query_vector = provider.embed(["redis caching"])[0]

    # An impossible floor filters out even a genuine match.
    result = retrieval.retrieve_semantic(
        memories,
        "redis caching",
        vectors,
        query_vector,
        provider=provider.name,
        model=provider.model,
        relevance_floor=0.999,
    )

    assert result.matches == []


def test_no_floor_returns_ranked_results_even_when_scores_are_low() -> None:
    provider = LocalHashingProvider(dimensions=1024)
    memories = [
        make_memory("a", "We disabled Redis caching for user records."),
        make_memory("b", "Never log full card numbers."),
    ]
    vectors = {
        memory.id: vector
        for memory, vector in zip(memories, provider.embed([m.content for m in memories]))
    }

    result = retrieval.retrieve_semantic(
        memories,
        "redis caching",
        vectors,
        provider.embed(["redis caching"])[0],
        provider=provider.name,
        model=provider.model,
        relevance_floor=0.0,
    )

    assert result.matches
    assert any("No similarity floor is applied" in note for note in result.notes)
