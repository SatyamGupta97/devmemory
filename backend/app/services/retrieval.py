"""Keyword retrieval baseline.

BM25 over the memory collection. Chosen because it is the standard relevance
baseline: anything cleverer has to beat it to earn its place, and it is fully
explainable — every point of a memory's score comes from a named term, so the
tool can show *why* a memory was returned instead of asking for trust.

What this deliberately cannot do: match on meaning. A query about "caching" will
not find a memory that says "Redis was removed after balances went stale",
because the two share no words. That limitation is the point of the baseline —
it is the thing Phase 6 has to improve on, and Phase 7 has to measure.

No model calls, no embeddings, no I/O. Same inputs, same ranking, always.
"""

from __future__ import annotations

import math

from app.config import bm25_b, bm25_k1
from app.schemas import MatchedTerm, Memory, RetrievalMatch, RetrievalResult
from app.services.text import tokens

STRATEGY = "keyword-bm25"

NOTES = [
    "Keyword matching only: a memory that means the same thing in different words "
    "scores zero and is never returned.",
    "Scores are relevance ranks, not probabilities. A score of 4.1 does not mean the "
    "memory is right 4.1 times out of 10, or that it is correct at all.",
    "Scores are only comparable within a single query. Term frequencies change when "
    "the collection changes, so a score from one run is not comparable to another.",
    "Superseded memories are included and labelled: retrieving a retired decision as "
    "if it were current is exactly the failure this tool exists to expose.",
]


def _idf(document_count: int, document_frequency: int) -> float:
    """Inverse document frequency.

    A term appearing in every memory tells the ranking nothing, so it approaches
    zero. A term appearing in one memory is highly discriminative. The
    ``+0.5`` smoothing keeps the value positive and defined when a term appears
    in every document.
    """
    return math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))


def _explain(query_terms: list[str], matched: list[MatchedTerm], total_terms: int) -> str:
    """A sentence a reader can check against the evidence."""
    if not matched:
        return "No query terms appear in this memory."

    strongest = matched[0]
    listed = ", ".join(f"{term.term} (x{term.term_frequency})" for term in matched)
    return (
        f"Matched {len(matched)} of {total_terms} query term(s): {listed}. "
        f"Largest contribution from '{strongest.term}' "
        f"(idf {strongest.idf:.2f})."
    )


def retrieve(
    memories: list[Memory],
    query: str,
    limit: int | None = None,
    project: str | None = None,
) -> RetrievalResult:
    """Rank memories against a task query.

    ``memories`` is the candidate pool. Filtering by project happens before this
    call, so relevance is computed inside a single namespace: a term that is
    common in one project is judged against that project, not the whole store.
    """
    k1 = bm25_k1()
    b = bm25_b()

    document_tokens = [tokens(memory.content) for memory in memories]
    document_count = len(document_tokens)

    # Query terms in order of first appearance, de-duplicated: a term repeated in
    # the query should not be counted twice.
    query_terms: list[str] = []
    for term in tokens(query):
        if term not in query_terms:
            query_terms.append(term)

    if document_count == 0 or not query_terms:
        return RetrievalResult(
            query=query,
            strategy=STRATEGY,
            project=project,
            considered=0,
            returned=0,
            matches=[],
            unmatched_query_terms=query_terms,
            notes=NOTES,
        )

    average_length = sum(len(doc) for doc in document_tokens) / document_count

    # Document frequency of each query term across the candidate pool.
    document_frequency = {
        term: sum(1 for doc in document_tokens if term in set(doc)) for term in query_terms
    }

    matches: list[RetrievalMatch] = []
    matched_anywhere: set[str] = set()

    for memory, doc_tokens in zip(memories, document_tokens):
        length = len(doc_tokens)
        # Guard against a zero-length document and average.
        length_ratio = length / average_length if average_length > 0 else 1.0

        contributions: list[MatchedTerm] = []
        for term in query_terms:
            frequency = doc_tokens.count(term)
            if frequency == 0:
                continue
            term_idf = _idf(document_count, document_frequency[term] or 1)
            weight = frequency * (k1 + 1) / (
                frequency + k1 * (1 - b + b * length_ratio)
            )
            contributions.append(
                MatchedTerm(
                    term=term,
                    idf=round(term_idf, 4),
                    term_frequency=frequency,
                    contribution=round(term_idf * weight, 4),
                )
            )
            matched_anywhere.add(term)

        if not contributions:
            continue

        contributions.sort(key=lambda item: (-item.contribution, item.term))
        score = round(sum(item.contribution for item in contributions), 4)
        matches.append(
            RetrievalMatch(
                memory=memory,
                score=score,
                matched_terms=contributions,
                explanation=_explain(query_terms, contributions, len(query_terms)),
            )
        )

    # Highest score first; ties break on id so the order is reproducible.
    matches.sort(key=lambda match: (-match.score, match.memory.id))

    if limit is not None:
        matches = matches[:limit]

    return RetrievalResult(
        query=query,
        strategy=STRATEGY,
        project=project,
        considered=document_count,
        returned=len(matches),
        matches=matches,
        # Naming the terms that found nothing is how the tool explains a miss
        # instead of silently returning a short list.
        unmatched_query_terms=[term for term in query_terms if term not in matched_anywhere],
        notes=NOTES,
    )