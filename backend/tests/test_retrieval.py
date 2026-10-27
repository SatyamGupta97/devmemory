"""Keyword retrieval tests.

The baseline is deliberately simple, so these tests focus on the properties that
make it usable: it finds literal matches, it respects namespace boundaries, it
ranks reproducibly, and it can explain every point of a score.
"""

from datetime import datetime, timezone

import pytest

from app.schemas import Memory, MemoryCategory, MemoryStatus
from app.services import retrieval

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


def make_memory(
    memory_id: str,
    content: str,
    project: str = "payments-api",
    category: MemoryCategory = MemoryCategory.DECISION,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    superseded_by: str | None = None,
) -> Memory:
    return Memory(
        id=memory_id,
        content=content,
        category=category,
        source="test",
        project=project,
        created_at=NOW,
        updated_at=NOW,
        confidence=0.9,
        status=status,
        superseded_by=superseded_by,
    )


@pytest.fixture
def pool() -> list[Memory]:
    return [
        make_memory("a", "We disabled Redis caching for user records because stale "
                        "cache entries caused wrong account balances."),
        make_memory("b", "The user service uses PostgreSQL 15 for persistence."),
        make_memory("c", "Never log full card numbers or CVV values.",
                    category=MemoryCategory.CONSTRAINT),
        make_memory("d", "The reporting service uses DuckDB for nightly jobs.",
                    project="analytics"),
    ]


def test_a_literal_term_is_retrieved(pool: list[Memory]) -> None:
    result = retrieval.retrieve(pool, "postgresql")

    assert [match.memory.id for match in result.matches] == ["b"]


def test_matching_is_case_insensitive(pool: list[Memory]) -> None:
    result = retrieval.retrieve(pool, "POSTGRESQL")

    assert [match.memory.id for match in result.matches] == ["b"]


def test_memories_with_no_matching_terms_are_not_returned(
    pool: list[Memory],
) -> None:
    result = retrieval.retrieve(pool, "postgresql")

    assert "a" not in [match.memory.id for match in result.matches]
    assert result.returned == 1


def test_stopwords_alone_find_nothing(pool: list[Memory]) -> None:
    result = retrieval.retrieve(pool, "the and is of to")

    assert result.matches == []


def test_namespace_boundaries_are_respected(pool: list[Memory]) -> None:
    """Callers pass an already-filtered pool; a wrong project simply is not here."""
    payments = [memory for memory in pool if memory.project == "payments-api"]

    result = retrieval.retrieve(payments, "duckdb", project="payments-api")

    assert result.matches == []
    assert all(match.memory.project == "payments-api" for match in result.matches)


def test_ranking_is_reproducible(pool: list[Memory]) -> None:
    first = retrieval.retrieve(pool, "user service caching")
    second = retrieval.retrieve(pool, "user service caching")

    assert [match.memory.id for match in first.matches] == [
        match.memory.id for match in second.matches
    ]
    assert [match.score for match in first.matches] == [
        match.score for match in second.matches
    ]


def test_identical_scores_are_ordered_by_id() -> None:
    """Ties must not depend on dictionary or insertion order."""
    pool = [
        make_memory("z", "PostgreSQL is used here."),
        make_memory("a", "PostgreSQL is used here."),
        make_memory("m", "PostgreSQL is used here."),
    ]

    result = retrieval.retrieve(pool, "postgresql")

    assert [match.memory.id for match in result.matches] == ["a", "m", "z"]


def test_a_memory_matching_more_query_terms_outranks_one_matching_fewer() -> None:
    pool = [
        make_memory("both", "Redis caching is configured for the user records layer."),
        make_memory("one", "Redis is a datastore used somewhere in the platform."),
    ]

    result = retrieval.retrieve(pool, "redis caching")

    assert result.matches[0].memory.id == "both"


def test_score_is_the_sum_of_its_term_contributions(pool: list[Memory]) -> None:
    """The explanation must account for the whole score, not part of it."""
    result = retrieval.retrieve(pool, "user service caching")

    for match in result.matches:
        total = sum(term.contribution for term in match.matched_terms)
        assert match.score == pytest.approx(total, abs=0.001), match.memory.id


def test_every_matched_term_reports_its_own_evidence(pool: list[Memory]) -> None:
    match = retrieval.retrieve(pool, "caching user").matches[0]

    for term in match.matched_terms:
        assert term.term
        assert term.term_frequency >= 1
        assert term.contribution > 0


def test_explanation_names_the_matched_terms(pool: list[Memory]) -> None:
    match = next(
        match
        for match in retrieval.retrieve(pool, "caching").matches
        if match.memory.id == "a"
    )

    assert "caching" in match.explanation
    assert "Matched 1 of 1" in match.explanation


def test_terms_that_found_nothing_are_reported(pool: list[Memory]) -> None:
    """This is how the baseline explains a miss instead of silently returning less."""
    result = retrieval.retrieve(pool, "add caching to the user service")

    assert "add" in result.unmatched_query_terms
    assert "caching" not in result.unmatched_query_terms


def test_a_different_wording_is_missed_entirely(pool: list[Memory]) -> None:
    """The known limitation of keyword search, asserted rather than hidden."""
    pool.append(
        make_memory(
            "e",
            "We removed the in-memory account snapshot because balances could go "
            "stale after writes.",
        )
    )

    result = retrieval.retrieve(pool, "add caching to the user service")

    assert "e" not in [match.memory.id for match in result.matches]
    assert result.unmatched_query_terms == ["add"]


def test_a_query_made_only_of_stopwords_returns_nothing(pool: list[Memory]) -> None:
    result = retrieval.retrieve(pool, "the is and")

    assert result.matches == []
    assert result.unmatched_query_terms == []


def test_empty_pool_returns_no_matches() -> None:
    result = retrieval.retrieve([], "postgresql")

    assert result.matches == []
    assert result.considered == 0


def test_limit_caps_the_number_of_results(pool: list[Memory]) -> None:
    result = retrieval.retrieve(pool, "user service", limit=1)

    assert len(result.matches) == 1


def test_returned_count_matches_the_payload(pool: list[Memory]) -> None:
    result = retrieval.retrieve(pool, "user service")

    assert result.returned == len(result.matches)


def test_superseded_memories_are_returned_and_labelled() -> None:
    """Showing a retired decision is the point: hiding it would hide the problem."""
    pool = [
        make_memory(
            "old",
            "Background jobs are queued through Celery.",
            status=MemoryStatus.SUPERSEDED,
            superseded_by="new",
        ),
        make_memory("new", "Background jobs are queued through Dramatiq."),
    ]

    result = retrieval.retrieve(pool, "background jobs")

    # Both memories match both terms, so which one ranks first is a tie broken by
    # id. The behaviour under test is that the retired one is still returned, and
    # returned labelled.
    superseded = next(match for match in result.matches if match.memory.id == "old")
    assert superseded.memory.status is MemoryStatus.SUPERSEDED
    assert superseded.memory.superseded_by == "new"


def test_result_declares_its_strategy_and_limitations(pool: list[Memory]) -> None:
    result = retrieval.retrieve(pool, "postgresql", project="payments-api")

    assert result.strategy == "keyword-bm25"
    assert result.project == "payments-api"
    assert result.notes
    assert any("Keyword matching only" in note for note in result.notes)
    assert any("not probabilities" in note for note in result.notes)


def test_rare_terms_weigh_more_than_ubiquitous_ones() -> None:
    """A word in every memory says nothing about relevance."""
    pool = [
        make_memory("a", "The service does a thing with Redis."),
        make_memory("b", "The service does a thing with Kafka."),
        make_memory("c", "The service does a thing with PostgreSQL."),
    ]

    common = retrieval.retrieve(pool, "service").matches[0]
    rare = retrieval.retrieve(pool, "redis").matches[0]

    # "service" appears in every document, so its idf collapses towards zero.
    assert common.matched_terms[0].idf < rare.matched_terms[0].idf


def test_a_repeated_query_term_is_counted_once(pool: list[Memory]) -> None:
    once = retrieval.retrieve(pool, "postgresql")
    twice = retrieval.retrieve(pool, "postgresql postgresql")

    assert once.matches[0].score == pytest.approx(twice.matches[0].score)


def test_retrieval_does_not_modify_the_pool(pool: list[Memory]) -> None:
    before = [(memory.id, memory.content, memory.status) for memory in pool]

    retrieval.retrieve(pool, "user service")

    assert before == [(memory.id, memory.content, memory.status) for memory in pool]