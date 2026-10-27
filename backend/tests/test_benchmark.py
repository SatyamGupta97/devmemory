"""Benchmark tests.

The metric arithmetic is tested against hand-calculated examples, because a
metric that is quietly wrong is worse than no metric: it turns "looks reasonable"
into a number nobody can question.
"""

import datetime as dt

import pytest

from app.schemas import (
    BenchmarkDefinition,
    BenchmarkExpectation,
    BenchmarkQueryDefinition,
    Memory,
    MemoryCategory,
)
from app.services import benchmark
from app.services.text import content_key

STAMP = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def memory(memory_id: str, content: str, project: str = "payments-api") -> Memory:
    return Memory(
        id=memory_id,
        content=content,
        category=MemoryCategory.DECISION,
        source="test",
        project=project,
        created_at=STAMP,
        updated_at=STAMP,
        confidence=0.9,
    )


def query(
    expected: list[str],
    query_id: str = "q1",
    text: str = "a query",
    project: str = "payments-api",
    kind: str = "direct",
    k: int | None = None,
) -> BenchmarkQueryDefinition:
    return BenchmarkQueryDefinition(
        id=query_id,
        kind=kind,
        project=project,
        query=text,
        expected=[BenchmarkExpectation(content=item) for item in expected],
        k=k,
    )


def definition(*queries: BenchmarkQueryDefinition, default_k: int = 3) -> BenchmarkDefinition:
    return BenchmarkDefinition(
        version=1, description="test", default_k=default_k, queries=list(queries)
    )


def run_one(
    ranked: list[str],
    memories: list[Memory],
    expected: list[str],
    k: int = 3,
):
    index = benchmark._build_index(memories)
    return benchmark.evaluate_query(query(expected, k=k), ranked, index, k)


# --- precision --------------------------------------------------------------


def test_precision_counts_only_what_was_returned() -> None:
    """A system that returns one memory must not be scored out of k."""
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]

    case = run_one(["a"], pool, ["Alpha memory."], k=5)

    assert case.precision_at_k == 1.0
    assert case.returned_count == 1


def test_precision_of_two_relevant_out_of_three() -> None:
    pool = [
        memory("a", "Alpha memory."),
        memory("b", "Beta memory."),
        memory("c", "Gamma memory."),
    ]

    case = run_one(["a", "b", "c"], pool, ["Alpha memory.", "Gamma memory."], k=3)

    assert case.precision_at_k == pytest.approx(0.6667, abs=1e-4)
    assert case.recall_at_k == 1.0


def test_precision_is_zero_when_nothing_relevant_is_returned() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]

    case = run_one(["a"], pool, ["Beta memory."], k=1)

    assert case.precision_at_k == 0.0
    assert case.recall_at_k == 0.0


def test_precision_is_zero_when_nothing_is_returned_but_something_was_expected() -> (
    None
):
    pool = [memory("a", "Alpha memory.")]

    case = run_one([], pool, ["Alpha memory."], k=3)

    assert case.precision_at_k == 0.0
    assert case.recall_at_k == 0.0


# --- recall -----------------------------------------------------------------


def test_recall_counts_every_expected_memory() -> None:
    pool = [
        memory("a", "Alpha memory."),
        memory("b", "Beta memory."),
        memory("c", "Gamma memory."),
    ]

    case = run_one(["a"], pool, ["Alpha memory.", "Beta memory.", "Gamma memory."], k=3)

    assert case.recall_at_k == pytest.approx(1 / 3, abs=1e-4)
    assert case.precision_at_k == 1.0


def test_recall_ignores_results_below_the_cut_off() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]

    case = run_one(["a", "b"], pool, ["Beta memory."], k=1)

    assert case.recall_at_k == 0.0


def test_missed_lists_the_expected_content_that_was_not_found() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]

    case = run_one(["a"], pool, ["Alpha memory.", "Beta memory."], k=2)

    assert case.missed == ["Beta memory."]


def test_irrelevant_lists_what_was_returned_but_not_expected() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]

    case = run_one(["a", "b"], pool, ["Alpha memory."], k=2)

    assert case.irrelevant_retrieved == ["b"]


# --- reciprocal rank --------------------------------------------------------


def test_reciprocal_rank_of_first_position_is_one() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]

    case = run_one(["a", "b"], pool, ["Alpha memory."], k=2)

    assert case.first_relevant_rank == 1
    assert case.reciprocal_rank == 1.0


def test_reciprocal_rank_of_second_position_is_one_half() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]

    case = run_one(["a", "b"], pool, ["Beta memory."], k=2)

    assert case.first_relevant_rank == 2
    assert case.reciprocal_rank == 0.5


def test_reciprocal_rank_of_third_position_is_one_third() -> None:
    pool = [
        memory("a", "Alpha memory."),
        memory("b", "Beta memory."),
        memory("c", "Gamma memory."),
    ]

    case = run_one(["a", "b", "c"], pool, ["Gamma memory."], k=3)

    assert case.reciprocal_rank == pytest.approx(1 / 3, abs=1e-4)


def test_reciprocal_rank_is_zero_when_nothing_relevant_is_found() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]

    case = run_one(["a"], pool, ["Beta memory."], k=1)

    assert case.first_relevant_rank is None
    assert case.reciprocal_rank == 0.0


# --- empty expectations -----------------------------------------------------


def test_a_query_that_should_match_nothing_scores_one_when_nothing_is_returned() -> (
    None
):
    pool = [memory("a", "Alpha memory.")]

    case = run_one([], pool, [], k=3)

    assert case.precision_at_k == 1.0
    # Recall is undefined, not zero: there was nothing to recall.
    assert case.recall_at_k is None
    assert case.reciprocal_rank is None


def test_a_query_that_should_match_nothing_scores_zero_when_something_is_returned() -> (
    None
):
    pool = [memory("a", "Alpha memory.")]

    case = run_one(["a"], pool, [], k=3)

    assert case.precision_at_k == 0.0
    assert case.recall_at_k is None


def test_undefined_recall_is_excluded_from_the_mean_not_counted_as_zero() -> None:
    """Otherwise a benchmark with no-match queries would look artificially poor."""
    pool = [memory("a", "Alpha memory.")]
    definition_ = definition(
        query(["Alpha memory."], query_id="real"),
        query([], query_id="no-match"),
    )

    report = benchmark.run(
        definition_, pool, lambda q, p, k: ["a"], strategy="test", k=3
    )

    assert report.summary.mean_recall_at_k == 1.0


# --- unresolved expectations ------------------------------------------------


def test_an_expectation_that_resolves_to_nothing_invalidates_the_query() -> None:
    pool = [memory("a", "Alpha memory.")]

    case = run_one(["a"], pool, ["Alpha memory.", "This memory is not imported."], k=3)

    assert case.valid is False
    assert case.unresolved_expectations == ["This memory is not imported."]


def test_invalid_queries_are_excluded_from_the_aggregate() -> None:
    """A broken expectation must not silently inflate or deflate the score."""
    pool = [memory("a", "Alpha memory.")]
    definition_ = definition(
        query(["Alpha memory."], query_id="good"),
        query(["Missing memory."], query_id="broken"),
    )

    report = benchmark.run(
        definition_, pool, lambda q, p, k: ["a"], strategy="test", k=3
    )

    assert report.summary.valid_queries == 1
    assert report.summary.invalid_queries == 1
    assert report.summary.mean_recall_at_k == 1.0
    assert report.summary.unresolved_expectations == 1
    assert any("excluded" in note for note in report.notes)


def test_a_report_where_nothing_can_be_scored_says_so() -> None:
    definition_ = definition(query(["Missing memory."]))

    report = benchmark.run(
        definition_, [], lambda q, p, k: [], strategy="test", k=3
    )

    assert report.summary.valid_queries == 0
    assert report.summary.mean_precision_at_k == 0.0
    assert any("Import data/sample_memories.json" in note for note in report.notes)


# --- identity handling ------------------------------------------------------


def test_duplicate_memories_satisfy_one_expectation() -> None:
    """Two identical memories are one fact, not two retrieval targets."""
    pool = [
        memory("a", "The user service uses PostgreSQL 15."),
        memory("b", "The user service uses PostgreSQL 15."),
    ]

    case = run_one(["a", "b"], pool, ["The user service uses PostgreSQL 15."], k=2)

    assert case.expected_count == 1
    assert case.recall_at_k == 1.0
    assert case.irrelevant_retrieved == []


def test_expectations_match_on_content_not_on_database_id() -> None:
    """Ids change on re-import; the benchmark must survive that."""
    pool = [memory("a-brand-new-id", "Alpha memory.")]

    case = run_one(["a-brand-new-id"], pool, ["Alpha memory."], k=1)

    assert case.recall_at_k == 1.0


def test_returned_ids_outside_the_pool_are_ignored() -> None:
    pool = [memory("a", "Alpha memory.")]

    case = run_one(["a", "ghost"], pool, ["Alpha memory."], k=2)

    assert case.returned_count == 1
    assert case.irrelevant_retrieved == []


def test_content_key_ignores_case_and_punctuation() -> None:
    assert content_key("Alpha memory.") == content_key("  alpha   MEMORY ")


# --- aggregation ------------------------------------------------------------


def test_aggregate_metrics_average_the_per_query_values() -> None:
    pool = [
        memory("a", "Alpha memory."),
        memory("b", "Beta memory."),
        memory("c", "Gamma memory."),
    ]
    definition_ = definition(
        query(["Alpha memory."], query_id="first", text="first query"),
        query(["Gamma memory."], query_id="second", text="second query"),
    )
    # First query: relevant at rank 1 -> P=1.0 (returned 1), R=1.0, RR=1.0
    # Second query: relevant at rank 2 -> P=0.5, R=1.0, RR=0.5
    rankings = {
        "first query": ["a"],
        "second query": ["a", "c"],
    }

    report = benchmark.run(
        definition_,
        pool,
        lambda q, p, k: rankings[q],
        strategy="test",
        k=3,
    )

    assert report.summary.mean_precision_at_k == 0.75
    assert report.summary.mean_recall_at_k == 1.0
    assert report.summary.mrr == 0.75


def test_totals_count_missed_and_irrelevant() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]
    definition_ = definition(
        query(["Alpha memory.", "Beta memory."], query_id="one"),
    )

    report = benchmark.run(
        definition_, pool, lambda q, p, k: ["a"], strategy="test", k=2
    )

    assert report.summary.total_missed == 1
    assert report.summary.total_irrelevant_retrieved == 0


def test_the_cut_off_is_recorded_in_every_case() -> None:
    pool = [memory("a", "Alpha memory.")]
    definition_ = definition(query(["Alpha memory."], query_id="one", k=7))

    report = benchmark.run(
        definition_, pool, lambda q, p, k: ["a"], strategy="test", k=3
    )

    assert report.cases[0].k == 7


def test_a_query_specific_cut_off_overrides_the_default() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]
    definition_ = definition(
        query(["Beta memory."], query_id="one", k=1),
        default_k=5,
    )
    seen: list[int] = []

    def rank(q: str, p: str | None, k: int) -> list[str]:
        seen.append(k)
        return ["a", "b"]

    report = benchmark.run(definition_, pool, rank, strategy="test", k=9)

    # The query's own cut-off wins over the run-level default of 9.
    assert seen == [1]
    assert report.cases[0].k == 1


# --- strategy plumbing ------------------------------------------------------


def test_both_strategies_receive_the_same_queries_and_ground_truth() -> None:
    pool = [memory("a", "Alpha memory.")]
    definition_ = definition(
        query(["Alpha memory."], query_id="one", project="payments-api"),
        query(["Alpha memory."], query_id="two", project="payments-api"),
    )
    received: list[list[tuple[str, str | None, int]]] = []

    for strategy in ("keyword", "semantic"):
        calls: list[tuple[str, str | None, int]] = []
        benchmark.run(
            definition_,
            pool,
            lambda q, p, k: (calls.append((q, p, k)), ["a"])[1],
            strategy=strategy,
            k=3,
        )
        received.append(calls)

    assert received[0] == received[1]


def test_the_report_states_which_strategy_was_measured() -> None:
    definition_ = definition(query([], query_id="one"))

    report = benchmark.run(
        definition_, [], lambda q, p, k: [], strategy="semantic-embedding", k=3
    )

    assert report.strategy == "semantic-embedding"


def test_metrics_are_reproducible() -> None:
    pool = [memory("a", "Alpha memory."), memory("b", "Beta memory.")]
    definition_ = definition(query(["Beta memory."], query_id="one"))

    first = benchmark.run(
        definition_, pool, lambda q, p, k: ["a", "b"], strategy="test", k=3
    )
    second = benchmark.run(
        definition_, pool, lambda q, p, k: ["a", "b"], strategy="test", k=3
    )

    assert first.summary.model_dump() == second.summary.model_dump()


def test_report_declares_its_limitations() -> None:
    definition_ = definition(query([], query_id="one"))

    report = benchmark.run(definition_, [], lambda q, p, k: [], strategy="test", k=3)

    assert any("cannot prove general retrieval quality" in note for note in report.notes)


# --- the real benchmark file ------------------------------------------------


def test_the_shipped_benchmark_file_is_valid() -> None:
    definition_ = benchmark.load_definition()

    assert definition_.version >= 1
    assert len(definition_.queries) >= 8
    assert definition_.default_k >= 1
    # Every case type the project claims to cover is present.
    kinds = {item.kind for item in definition_.queries}
    assert {"direct", "paraphrase", "contradiction", "project_boundary", "irrelevant"} <= kinds


def test_the_shipped_benchmark_ids_are_unique() -> None:
    definition_ = benchmark.load_definition()

    ids = [item.id for item in definition_.queries]
    assert len(ids) == len(set(ids))


def test_every_shipped_expectation_resolves_against_the_sample_dataset() -> None:
    """Guards the benchmark file against drift from the sample data.

    If a sample memory is reworded, this fails instead of the benchmark quietly
    scoring a query against incomplete ground truth.
    """
    import json
    from pathlib import Path

    sample = Path(__file__).resolve().parents[2] / "data" / "sample_memories.json"
    contents = {
        content_key(entry["content"]) for entry in json.loads(sample.read_text())
    }

    definition_ = benchmark.load_definition()
    unresolved = [
        (item.id, expectation.content)
        for item in definition_.queries
        for expectation in item.expected
        if content_key(expectation.content) not in contents
    ]

    assert unresolved == []


def test_a_missing_benchmark_file_is_reported_clearly(tmp_path) -> None:
    with pytest.raises(benchmark.BenchmarkError, match="not found"):
        benchmark.load_definition(tmp_path / "nope.json")


def test_a_malformed_benchmark_file_is_reported_clearly(tmp_path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{ not json")

    with pytest.raises(benchmark.BenchmarkError, match="not valid JSON"):
        benchmark.load_definition(path)