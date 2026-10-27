"""Report composition tests.

The central claim of this phase is that the report invents nothing. These tests
hold it to that: counts must match the data, and recommendations must cite the
numbers that produced them.
"""

import datetime as dt

import pytest

from app.schemas import (
    AiAnalysisReport,
    AiFinding,
    AiIssueType,
    BenchmarkCaseResult,
    BenchmarkReport,
    BenchmarkSummary,
    EmbeddingStatus,
    HealthReport,
    Memory,
    MemoryCategory,
    MemoryStatus,
    Severity,
)
from app.services import report

STAMP = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def memory(
    memory_id: str,
    content: str = "A memory.",
    project: str = "payments-api",
    category: MemoryCategory = MemoryCategory.DECISION,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    confidence: float | None = 0.9,
) -> Memory:
    return Memory(
        id=memory_id,
        content=content,
        category=category,
        source="test",
        project=project,
        created_at=STAMP,
        updated_at=STAMP,
        confidence=confidence,
        status=status,
    )


def empty_health() -> HealthReport:
    return HealthReport(
        generated_at=STAMP,
        analyzer="deterministic-rules",
        total_memories=0,
        projects=[],
        summary={},
        findings=[],
        limitations=[],
    )


def benchmark_report(recall: float | None = 1.0, missed: int = 0, k: int = 5) -> BenchmarkReport:
    cases = [
        BenchmarkCaseResult(
            query_id="q1",
            kind="direct",
            project="payments-api",
            query="a query",
            k=k,
            valid=True,
            expected_count=1,
            returned_count=1,
            relevant_retrieved=["m1"],
            missed=["A missed memory."] if missed else [],
            irrelevant_retrieved=[],
            unresolved_expectations=[],
            precision_at_k=1.0,
            recall_at_k=recall if recall is not None else 0.0,
            reciprocal_rank=1.0,
            first_relevant_rank=1,
        )
    ]
    return BenchmarkReport(
        generated_at=STAMP,
        strategy="keyword-bm25",
        summary=BenchmarkSummary(
            strategy="keyword-bm25",
            k=k,
            query_count=1,
            valid_queries=1,
            invalid_queries=0,
            mean_precision_at_k=1.0,
            mean_recall_at_k=recall,
            mrr=1.0,
            total_missed=missed,
            total_irrelevant_retrieved=0,
            unresolved_expectations=0,
        ),
        cases=cases,
        notes=[],
    )


def embedding_status(
    captures_meaning: bool = False, indexed: int = 2, stale: int = 0
) -> EmbeddingStatus:
    return EmbeddingStatus(
        provider="local" if not captures_meaning else "hosted",
        model="hashed-ngrams-1024" if not captures_meaning else "text-embedding-3-small",
        dimensions=1024,
        captures_meaning=captures_meaning,
        description="test",
        total_memories=2,
        indexed_memories=indexed,
        stale_memories=stale,
    )


def build(memories, health=None, benchmark=None, embedding=None, ai=None, reason=None, semantic=None):
    return report.build(
        memories,
        health or empty_health(),
        benchmark or benchmark_report(),
        embedding or embedding_status(),
        ai,
        reason,
        benchmark_version=1,
        benchmark_query_count=1,
        semantic=semantic,
    )


# --- inventory --------------------------------------------------------------


def test_inventory_counts_the_memories_it_was_given() -> None:
    memories = [
        memory("a", project="payments-api", category=MemoryCategory.DECISION),
        memory("b", project="analytics", category=MemoryCategory.FAILURE),
        memory("c", project="analytics", category=MemoryCategory.FAILURE),
    ]

    result = report.inventory(memories)

    assert result.total == 3
    assert result.by_project == {"analytics": 2, "payments-api": 1}
    assert result.by_category == {"decision": 1, "failure": 2}


def test_inventory_counts_confidence_honestly() -> None:
    memories = [memory("a", confidence=0.9), memory("b", confidence=None)]

    result = report.inventory(memories)

    assert result.with_confidence == 1
    assert result.without_confidence == 1


def test_inventory_of_nothing_is_zero_not_missing() -> None:
    result = report.inventory([])

    assert result.total == 0
    assert result.by_project == {}
    assert result.by_status == {}


def test_inventory_tracks_status() -> None:
    memories = [
        memory("a"),
        memory("b", status=MemoryStatus.SUPERSEDED),
    ]

    result = report.inventory(memories)

    assert result.by_status == {"active": 1, "superseded": 1}


# --- missed examples --------------------------------------------------------


def test_missed_examples_come_from_benchmark_cases() -> None:
    examples = report.missed_examples(benchmark_report(recall=0.5, missed=1))

    assert len(examples) == 1
    assert examples[0].query_id == "q1"
    assert examples[0].missed == ["A missed memory."]


def test_no_misses_means_no_examples() -> None:
    assert report.missed_examples(benchmark_report(missed=0)) == []


def test_invalid_cases_are_not_offered_as_retrieval_failures() -> None:
    """A query with broken ground truth cannot demonstrate a retrieval failure."""
    benchmark = benchmark_report(recall=0.0, missed=1)
    benchmark.cases[0].valid = False

    assert report.missed_examples(benchmark) == []


# --- recommendations --------------------------------------------------------


def one_finding(issue_type: str, title: str = "x"):
    from app.schemas import HealthFinding

    return HealthFinding(
        id=f"{issue_type}:m1",
        issue_type=issue_type,
        severity=Severity.MEDIUM,
        title=title,
        explanation="because",
        evidence=["evidence"],
        memory_ids=["m1"],
        suggested_action="do something",
    )


def health_with(*issue_types: str) -> HealthReport:
    findings = [one_finding(item) for item in issue_types]
    summary: dict[str, int] = {}
    for item in issue_types:
        summary[item] = summary.get(item, 0) + 1
    return HealthReport(
        generated_at=STAMP,
        analyzer="deterministic-rules",
        total_memories=1,
        projects=["payments-api"],
        summary=summary,
        findings=findings,
        limitations=[],
    )


def test_suspicious_content_is_the_first_recommendation() -> None:
    recommendations = report.recommendations(
        [memory("m1")],
        health_with("suspicious_content", "potential_contradiction"),
        benchmark_report(),
        None,
        embedding_status(),
        report.AiSection(consulted=False, reason="not configured"),
    )

    assert recommendations[0].priority == "high"
    assert "untrusted" in recommendations[0].title


def test_recommendations_cite_the_real_count() -> None:
    health = health_with("potential_contradiction", "potential_contradiction")

    recommendations = report.recommendations(
        [memory("m1")],
        health,
        benchmark_report(),
        None,
        embedding_status(),
        report.AiSection(consulted=False),
    )

    contradiction = next(
        item for item in recommendations if "contradiction" in item.title
    )
    assert "2" in contradiction.title
    assert len(contradiction.related) == 2


def test_a_missed_retrieval_produces_a_recommendation() -> None:
    recommendations = report.recommendations(
        [memory("m1")],
        empty_health(),
        benchmark_report(recall=0.5, missed=2),
        None,
        embedding_status(),
        report.AiSection(consulted=False),
    )

    assert any("missed 2" in item.title.lower() for item in recommendations)


def test_stale_embeddings_produce_a_recommendation() -> None:
    recommendations = report.recommendations(
        [memory("m1")],
        empty_health(),
        benchmark_report(),
        None,
        embedding_status(indexed=0, stale=2),
        report.AiSection(consulted=False),
    )

    assert any("Index 2" in item.title for item in recommendations)


def test_a_surface_provider_is_called_out_as_not_semantic() -> None:
    recommendations = report.recommendations(
        [memory("m1")],
        empty_health(),
        benchmark_report(),
        None,
        embedding_status(captures_meaning=False, indexed=2),
        report.AiSection(consulted=False),
    )

    assert any("hosted embedding model" in item.title for item in recommendations)


def test_a_meaning_capturing_provider_is_not_called_out() -> None:
    recommendations = report.recommendations(
        [memory("m1")],
        empty_health(),
        benchmark_report(),
        None,
        embedding_status(captures_meaning=True, indexed=2),
        report.AiSection(consulted=True),
    )

    assert not any("hosted embedding model" in item.title for item in recommendations)


def test_unconsulted_ai_is_reported_as_a_gap() -> None:
    recommendations = report.recommendations(
        [memory("m1")],
        empty_health(),
        benchmark_report(),
        None,
        embedding_status(),
        report.AiSection(consulted=False, reason="not configured"),
    )

    gap = next(item for item in recommendations if "language model" in item.title)
    assert "not configured" in gap.rationale


def test_an_empty_collection_says_so_instead_of_pretending_all_is_well() -> None:
    recommendations = report.recommendations(
        [],
        empty_health(),
        benchmark_report(recall=None, missed=0),
        None,
        embedding_status(indexed=0),
        report.AiSection(consulted=False),
    )

    import_item = next(
        item for item in recommendations if "Import" in item.title
    )
    assert "empty" in import_item.rationale.lower()


def test_a_clean_collection_still_disclaims_perfection() -> None:
    recommendations = report.recommendations(
        [memory("m1")],
        empty_health(),
        benchmark_report(),
        None,
        embedding_status(captures_meaning=True),
        report.AiSection(consulted=True),
    )

    clean = next(item for item in recommendations if "No problems" in item.title)
    assert "not proof of quality" in clean.rationale


def test_recommendations_are_ordered_by_priority() -> None:
    recommendations = report.recommendations(
        [memory("m1")],
        health_with("unreliable_source", "suspicious_content", "near_duplicate"),
        benchmark_report(),
        None,
        embedding_status(),
        report.AiSection(consulted=False),
    )

    priorities = [item.priority for item in recommendations]
    assert priorities == sorted(priorities, key=["high", "medium", "low"].index)


# --- composition ------------------------------------------------------------


def test_the_report_labels_ai_findings_as_model_output() -> None:
    ai = AiAnalysisReport(
        generated_at=STAMP,
        provider="hosted",
        model="test-model",
        analyzed_memories=1,
        excluded_memories=[],
        findings=[
            AiFinding(
                id="ai-0",
                issue_type=AiIssueType.SEMANTIC_DUPLICATE,
                severity=Severity.MEDIUM,
                title="Same lesson twice",
                explanation="Both describe the same failure.",
                evidence=["a", "b"],
                memory_ids=["m1"],
                suggested_action="merge",
                uncertainty="low",
            )
        ,
        ],
        rejected=[],
        notes=[],
    )

    result = build([memory("m1")], ai=ai)

    assert result.ai.consulted is True
    assert result.ai.model == "test-model"
    assert result.ai.findings[0].source == "model"
    # Deterministic findings stay separately identifiable.
    assert all(finding.source == "rule" for finding in result.health.findings)


def test_the_report_states_when_no_model_was_consulted() -> None:
    result = build([memory("m1")], reason="not configured")

    assert result.ai.consulted is False
    assert result.ai.reason == "not configured"
    assert any("No language model was consulted" in note for note in result.notes)


def test_the_report_records_the_measurement_context() -> None:
    result = build(
        [memory("m1")],
        embedding=embedding_status(captures_meaning=False, indexed=1),
        semantic=benchmark_report(),
    )

    context = result.context
    assert context.benchmark_version == 1
    assert context.benchmark_query_count == 1
    assert context.benchmark_k == 5
    assert context.embedding_provider == "local"
    assert context.embedding_captures_meaning is False
    assert "semantic-embedding" in context.retrieval_strategy


def test_a_surface_provider_puts_a_caveat_in_the_notes() -> None:
    result = build([memory("m1")], embedding=embedding_status(captures_meaning=False))

    assert any("surface-form provider" in note for note in result.notes)


def test_no_caveat_is_needed_for_a_meaning_capturing_provider() -> None:
    result = build([memory("m1")], embedding=embedding_status(captures_meaning=True))

    assert not any("surface-form provider" in note for note in result.notes)


def test_semantic_results_are_optional() -> None:
    result = build([memory("m1")])

    assert result.retrieval.semantic is None


def test_the_report_reports_the_scope_it_was_built_for() -> None:
    result = report.build(
        [memory("m1")],
        empty_health(),
        benchmark_report(),
        embedding_status(),
        None,
        None,
        benchmark_version=1,
        benchmark_query_count=1,
        scope_project="payments-api",
    )

    assert result.scope_project == "payments-api"