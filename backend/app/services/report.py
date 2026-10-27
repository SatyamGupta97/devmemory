"""The consolidated inspector report.

One document that answers: what memories exist, what is wrong with them, whether
retrieval finds the right ones, and what to do next.

Two rules govern this module:

1. **It computes nothing of its own.** Inventory counts come from the memories,
   findings from the health analyser, metrics from the benchmark. The report is a
   composition, so a number in the report cannot disagree with the number on the
   screen next to it.

2. **Every recommendation cites the count that justifies it.** A suggestion with
   no evidence is an opinion, and this tool's whole value is that it does not
   offer those.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import stale_after_days
from app.schemas import (
    AiAnalysisReport,
    AiSection,
    BenchmarkReport,
    EmbeddingStatus,
    HealthReport,
    InspectorReport,
    InventoryBreakdown,
    Memory,
    MissedExample,
    ReportBenchmark,
    ReportContext,
    ReportRecommendation,
)

#: How many retrieval failures to show as examples. Enough to be concrete,
#: few enough to read.
MAX_MISSED_EXAMPLES = 5

NOTES = [
    "Every count and metric in this report was computed from the stored data at "
    "the time shown. Nothing here is illustrative.",
    "Findings are suggestions for a human. This report changes nothing by itself.",
    "Benchmark scores describe these queries on this collection; they are not a "
    "general measure of retrieval quality.",
]


def inventory(memories: list[Memory]) -> InventoryBreakdown:
    by_project: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_status: dict[str, int] = {}
    with_confidence = 0

    for memory in memories:
        by_project[memory.project] = by_project.get(memory.project, 0) + 1
        by_category[memory.category.value] = (
            by_category.get(memory.category.value, 0) + 1
        )
        by_status[memory.status.value] = by_status.get(memory.status.value, 0) + 1
        if memory.confidence is not None:
            with_confidence += 1

    return InventoryBreakdown(
        total=len(memories),
        by_project=dict(sorted(by_project.items())),
        by_category=dict(sorted(by_category.items())),
        by_status=dict(sorted(by_status.items())),
        with_confidence=with_confidence,
        without_confidence=len(memories) - with_confidence,
    )


def missed_examples(
    benchmark: BenchmarkReport, limit: int = MAX_MISSED_EXAMPLES
) -> list[MissedExample]:
    """Retrieval failures, taken from the benchmark rather than invented.

    Only valid queries are considered: a query whose ground truth did not resolve
    cannot demonstrate a retrieval failure.
    """
    examples = [
        MissedExample(
            query_id=case.query_id,
            query=case.query,
            missed=case.missed,
            expected_count=case.expected_count,
        )
        for case in benchmark.cases
        if case.valid and case.missed
    ]
    return examples[:limit]


def recommendations(
    memories: list[Memory],
    health: HealthReport,
    benchmark: BenchmarkReport,
    semantic: BenchmarkReport | None,
    embedding: EmbeddingStatus,
    ai: AiSection,
) -> list[ReportRecommendation]:
    """Derive next actions from the numbers actually present."""
    summary = health.summary
    items: list[ReportRecommendation] = []

    suspicious = summary.get("suspicious_content", 0)
    if suspicious:
        items.append(
            ReportRecommendation(
                priority="high",
                title=f"Treat {suspicious} memory/memories as untrusted",
                rationale=(
                    f"{suspicious} memory/memories contain text that reads like "
                    "instructions. They are stored data, not commands: review them "
                    "before any agent sees them."
                ),
                related=[
                    finding.id
                    for finding in health.findings
                    if finding.issue_type.value == "suspicious_content"
                ],
            )
        )

    contradictions = summary.get("potential_contradiction", 0)
    if contradictions:
        items.append(
            ReportRecommendation(
                priority="high",
                title=f"Resolve {contradictions} potential contradiction(s)",
                rationale=(
                    f"{contradictions} finding(s) pair memories that name different "
                    "values for the same subject. Only one can be current; the rest "
                    "should be superseded rather than deleted."
                ),
                related=[
                    finding.id
                    for finding in health.findings
                    if finding.issue_type.value == "potential_contradiction"
                ],
            )
        )

    duplicates = summary.get("exact_duplicate", 0) + summary.get("near_duplicate", 0)
    if duplicates:
        items.append(
            ReportRecommendation(
                priority="medium",
                title=f"Merge or remove {duplicates} duplicate finding(s)",
                rationale=(
                    f"{summary.get('exact_duplicate', 0)} exact and "
                    f"{summary.get('near_duplicate', 0)} near-duplicate finding(s) "
                    "split one fact across several memories."
                ),
                related=[
                    finding.id
                    for finding in health.findings
                    if finding.issue_type.value in {"exact_duplicate", "near_duplicate"}
                ],
            )
        )

    stale = summary.get("potentially_stale", 0)
    if stale:
        items.append(
            ReportRecommendation(
                priority="medium",
                title=f"Review {stale} potentially stale memory/memories",
                rationale=(
                    f"{stale} memory/memories are older than {stale_after_days()} "
                    "days. Age alone is not proof of error, so confirm each against "
                    "its source."
                ),
                related=[
                    finding.id
                    for finding in health.findings
                    if finding.issue_type.value == "potentially_stale"
                ],
            )
        )

    recall = benchmark.summary.mean_recall_at_k
    missed_total = benchmark.summary.total_missed
    if recall is not None and missed_total:
        items.append(
            ReportRecommendation(
                priority="medium",
                title=f"Retrieval missed {missed_total} expected memory/memories",
                rationale=(
                    f"Mean recall@{benchmark.summary.k} is {recall:.3f}. The missed "
                    "memories are listed under retrieval examples; a missed decision "
                    "is a mistake an agent will repeat."
                ),
                related=[case.query_id for case in benchmark.cases if case.missed],
            )
        )

    if embedding.stale_memories:
        items.append(
            ReportRecommendation(
                priority="medium",
                title=f"Index {embedding.stale_memories} memory/memories for semantic search",
                rationale=(
                    f"{embedding.stale_memories} of {embedding.total_memories} "
                    "memories have no current vector, so semantic retrieval silently "
                    "excludes them."
                ),
            )
        )

    if not embedding.captures_meaning and embedding.indexed_memories:
        items.append(
            ReportRecommendation(
                priority="low",
                title="Configure a hosted embedding model for a real semantic baseline",
                rationale=(
                    f"The active provider ('{embedding.model}') compares surface "
                    "form, so the semantic numbers above are not a test of meaning "
                    "based retrieval. Re-index with a hosted model to measure that."
                ),
            )
        )

    if not ai.consulted:
        items.append(
            ReportRecommendation(
                priority="low",
                title="Configure a language model for meaning-based findings",
                rationale=(
                    "AI analysis is not configured, so paraphrase duplicates and "
                    "differently-worded contradictions were not checked. "
                    + (ai.reason or "")
                ).strip(),
            )
        )

    weak_sources = summary.get("unreliable_source", 0)
    if weak_sources:
        items.append(
            ReportRecommendation(
                priority="low",
                title=f"Replace {weak_sources} unverifiable source reference(s)",
                rationale=(
                    f"{weak_sources} memory/memories point at a source that cannot be "
                    "re-opened, so they cannot be confirmed or corrected."
                ),
                related=[
                    finding.id
                    for finding in health.findings
                    if finding.issue_type.value == "unreliable_source"
                ],
            )
        )

    if not memories:
        items.append(
            ReportRecommendation(
                priority="low",
                title="Import some memories to inspect",
                rationale=(
                    "The collection is empty, so every check above ran on nothing. "
                    "Import data/sample_memories.json to see the tool work."
                ),
            )
        )
    elif not items:
        items.append(
            ReportRecommendation(
                priority="low",
                title="No problems detected by the current rules",
                rationale=(
                    f"All {len(memories)} memories passed every deterministic check "
                    "and the benchmark found no missed memories. That is not proof of "
                    "quality: the rules and the benchmark only cover what they cover."
                ),
            )
        )

    if semantic is not None:
        keyword_recall = benchmark.summary.mean_recall_at_k
        semantic_recall = semantic.summary.mean_recall_at_k
        if keyword_recall is not None and semantic_recall is not None:
            direction = (
                "higher" if semantic_recall > keyword_recall
                else "lower" if semantic_recall < keyword_recall
                else "identical"
            )
            items.append(
                ReportRecommendation(
                    priority="low",
                    title=f"Semantic recall is {direction} than keyword recall",
                    rationale=(
                        f"Keyword recall@{benchmark.summary.k} is "
                        f"{keyword_recall:.3f}; semantic is {semantic_recall:.3f}. "
                        "Compare precision before switching: a recall gain bought "
                        "with precision may not be worth it."
                    ),
                )
            )

    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: order.get(item.priority, 3))
    return items


def build(
    memories: list[Memory],
    health: HealthReport,
    benchmark: BenchmarkReport,
    embedding: EmbeddingStatus,
    ai_report: AiAnalysisReport | None,
    ai_unavailable_reason: str | None,
    benchmark_version: int,
    benchmark_query_count: int,
    semantic: BenchmarkReport | None = None,
    now: datetime | None = None,
    scope_project: str | None = None,
) -> InspectorReport:
    """Compose the report from parts that were each computed elsewhere."""
    ai = AiSection(
        consulted=ai_report is not None,
        model=ai_report.model if ai_report else None,
        reason=None if ai_report else ai_unavailable_reason,
        findings=ai_report.findings if ai_report else [],
        rejected=ai_report.rejected if ai_report else [],
    )

    notes = list(NOTES)
    if not embedding.captures_meaning:
        notes.append(
            "Semantic metrics were produced by a surface-form provider, not a "
            "language model embedding. Treat them as a lower bound on what semantic "
            "retrieval can do."
        )
    if ai_report is None:
        notes.append(
            "No language model was consulted, so paraphrase-level problems are not "
            "covered by this report."
        )

    return InspectorReport(
        generated_at=now or datetime.now(timezone.utc),
        scope_project=scope_project,
        inventory=inventory(memories),
        health=health,
        ai=ai,
        retrieval=ReportBenchmark(
            keyword=benchmark,
            semantic=semantic,
            missed_examples=missed_examples(semantic or benchmark),
        ),
        recommendations=recommendations(
            memories, health, benchmark, semantic, embedding, ai
        ),
        context=ReportContext(
            retrieval_strategy="keyword-bm25"
            + ("+semantic-embedding" if semantic else ""),
            benchmark_version=benchmark_version,
            benchmark_query_count=benchmark_query_count,
            benchmark_k=benchmark.summary.k,
            embedding_provider=embedding.provider,
            embedding_model=embedding.model,
            embedding_captures_meaning=embedding.captures_meaning,
            embeddings_indexed=embedding.indexed_memories,
            embeddings_stale=embedding.stale_memories,
            ai_consulted=ai.consulted,
            ai_model=ai.model,
            ai_unavailable_reason=ai.reason,
        ),
        notes=notes,
    )