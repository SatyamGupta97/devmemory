"""Retrieval evaluation: measuring retrieval quality instead of admiring it.

Without this, the project can show two rankings but cannot say which is better.
Every metric here is computed from the actual ranked output, never hardcoded, and
the metric definitions are written down because "precision at 5" means different
things in different papers.

Definitions used here, for a cut-off ``k``:

* **precision@k** — of the memories actually returned in the top ``k``, what
  fraction were expected. The denominator is the number returned, not ``k``,
  because a system that returns nothing should not be rewarded for precision.
* **recall@k** — of the memories expected, what fraction appeared in the top
  ``k``.
* **reciprocal rank** — ``1 / rank`` of the first expected memory found, ``0.0``
  if none was found. Mean reciprocal rank (MRR) averages this over queries.

Two cases are defined explicitly rather than left to divide by zero:

* **No expected memories** (a query that *should* match nothing): precision is
  ``1.0`` when nothing was returned and ``0.0`` otherwise, and recall is ``None``
  — undefined, and excluded from the mean rather than counted as zero.
* **An expectation that resolves to no memory**: the query is marked invalid and
  excluded from the aggregate means. Scoring it anyway would report a
  misleadingly high recall for a benchmark entry that is simply broken.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import benchmark_default_k, benchmark_path
from app.schemas import (
    BenchmarkCaseResult,
    BenchmarkDefinition,
    BenchmarkReport,
    BenchmarkSummary,
    Memory,
)
from app.services.text import content_key

NOTES = [
    "Metrics come from the actual ranked output of the strategy under test.",
    "A benchmark with ten queries cannot prove general retrieval quality; it "
    "measures this collection and these queries.",
    "Recall of 1.0 means every expected memory was found, not that the ranking is "
    "correct — an irrelevant memory ranked first still costs precision.",
    "Queries whose expectations do not resolve to a stored memory are excluded "
    "from the aggregate, because their ground truth is incomplete.",
]


class BenchmarkError(RuntimeError):
    """The benchmark file is missing or malformed."""


def load_definition(path: Path | None = None) -> BenchmarkDefinition:
    """Read and validate the version-controlled benchmark file."""
    resolved = path or benchmark_path()
    if not resolved.exists():
        raise BenchmarkError(
            f"Benchmark file not found at {resolved}. Import the sample memories "
            "first, or set DEVMEMORY_BENCHMARK_PATH."
        )

    try:
        raw = json.loads(resolved.read_text())
    except json.JSONDecodeError as error:
        raise BenchmarkError(f"Benchmark file is not valid JSON: {error}") from error

    try:
        return BenchmarkDefinition.model_validate(raw)
    except Exception as error:  # noqa: BLE001 - surface pydantic's message
        raise BenchmarkError(f"Benchmark file is invalid: {error}") from error


@dataclass(frozen=True)
class _Index:
    """Lookups the evaluator needs, built once per run."""

    by_id: dict[str, Memory]
    keys_by_id: dict[str, str]
    ids_by_key: dict[str, list[str]]


def _build_index(memories: list[Memory]) -> _Index:
    keys_by_id: dict[str, str] = {}
    ids_by_key: dict[str, list[str]] = {}

    for memory in memories:
        key = content_key(memory.content)
        keys_by_id[memory.id] = key
        ids_by_key.setdefault(key, []).append(memory.id)

    return _Index(
        by_id={memory.id: memory for memory in memories},
        keys_by_id=keys_by_id,
        ids_by_key=ids_by_key,
    )


def evaluate_query(
    definition,
    ranked_ids: list[str],
    index: _Index,
    k: int,
) -> BenchmarkCaseResult:
    """Score one query against one ranked list of memory ids.

    Relevance is compared on content keys, not ids, so two identical memories
    both satisfy a single expectation instead of competing with each other.
    """
    expected_keys = {content_key(item.content) for item in definition.expected}

    unresolved = [
        item.content for item in definition.expected if content_key(item.content) not in index.ids_by_key
    ]

    top_k = ranked_ids[:k]
    # Ignore ids the strategy returned that are not in the candidate pool.
    top_k = [memory_id for memory_id in top_k if memory_id in index.keys_by_id]

    retrieved_keys = [index.keys_by_id[memory_id] for memory_id in top_k]
    hits = expected_keys & set(retrieved_keys)

    first_rank = next(
        (
            position
            for position, key in enumerate(retrieved_keys, start=1)
            if key in expected_keys
        ),
        None,
    )

    if expected_keys:
        precision = len(hits) / len(top_k) if top_k else 0.0
        recall: float | None = len(hits) / len(expected_keys)
        reciprocal = 1.0 / first_rank if first_rank else 0.0
    else:
        # A query that should match nothing. Returning nothing is the correct
        # answer; returning anything is a false positive.
        precision = 1.0 if not top_k else 0.0
        recall = None
        reciprocal = None

    missed = [
        item.content
        for item in definition.expected
        if content_key(item.content) not in hits
    ]

    # A query can only be scored when there was something to rank. With an empty
    # pool, "returned nothing" is vacuous: a no-match query would report perfect
    # precision while testing nothing at all.
    return BenchmarkCaseResult(
        query_id=definition.id,
        kind=definition.kind,
        project=definition.project,
        query=definition.query,
        k=k,
        valid=not unresolved and bool(index.by_id),
        expected_count=len(expected_keys),
        returned_count=len(top_k),
        relevant_retrieved=[
            memory_id
            for memory_id in top_k
            if index.keys_by_id[memory_id] in expected_keys
        ],
        missed=missed,
        irrelevant_retrieved=[
            memory_id
            for memory_id in top_k
            if index.keys_by_id[memory_id] not in expected_keys
        ],
        unresolved_expectations=unresolved,
        precision_at_k=round(precision, 4),
        recall_at_k=None if recall is None else round(recall, 4),
        reciprocal_rank=None if reciprocal is None else round(reciprocal, 4),
        first_relevant_rank=first_rank,
    )


def run(
    definition: BenchmarkDefinition,
    memories: list[Memory],
    rank: Callable[[str, str | None, int], list[str]],
    strategy: str,
    k: int | None = None,
    now: datetime | None = None,
) -> BenchmarkReport:
    """Run every benchmark query through a strategy and aggregate the metrics.

    ``rank(query, project, k)`` returns ranked memory ids. Passing the strategy
    in as a function is what guarantees both strategies are measured on the same
    queries, the same ground truth and the same cut-off.
    """
    cut_off = k or definition.default_k or benchmark_default_k()
    index = _build_index(memories)

    cases: list[BenchmarkCaseResult] = []
    for query in definition.queries:
        ranked = rank(query.query, query.project, query.k or cut_off)
        cases.append(evaluate_query(query, ranked, index, query.k or cut_off))

    valid = [case for case in cases if case.valid]
    scoreable_recall = [case for case in valid if case.recall_at_k is not None]
    scoreable_rr = [case for case in valid if case.reciprocal_rank is not None]

    summary = BenchmarkSummary(
        strategy=strategy,
        k=cut_off,
        query_count=len(cases),
        valid_queries=len(valid),
        invalid_queries=len(cases) - len(valid),
        mean_precision_at_k=round(
            sum(case.precision_at_k for case in valid) / len(valid), 4
        )
        if valid
        else 0.0,
        mean_recall_at_k=round(
            sum(float(case.recall_at_k) for case in scoreable_recall)
            / len(scoreable_recall),
            4,
        )
        if scoreable_recall
        else None,
        mrr=round(
            sum(float(case.reciprocal_rank) for case in scoreable_rr)
            / len(scoreable_rr),
            4,
        )
        if scoreable_rr
        else None,
        total_missed=sum(len(case.missed) for case in valid),
        total_irrelevant_retrieved=sum(
            len(case.irrelevant_retrieved) for case in valid
        ),
        unresolved_expectations=sum(
            len(case.unresolved_expectations) for case in cases
        ),
    )

    notes = list(NOTES)
    if not memories:
        notes.insert(
            0,
            "The candidate pool is empty, so no query can be scored: 'returned "
            "nothing' is vacuous when there was nothing to rank.",
        )
    if summary.invalid_queries:
        notes.insert(
            0,
            f"{summary.invalid_queries} query/queries were excluded because their "
            "expectations do not resolve to a stored memory. Import the sample "
            "dataset, or fix the benchmark file.",
        )
    if not valid:
        notes.insert(
            0,
            "No query could be scored. Import data/sample_memories.json before "
            "running the benchmark.",
        )

    return BenchmarkReport(
        generated_at=now or datetime.now(timezone.utc),
        strategy=strategy,
        summary=summary,
        cases=cases,
        notes=notes,
    )