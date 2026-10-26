"""Memory health analysis.

Deterministic rules only. No model is called, and nothing is ever written:
this module takes a list of memories and returns findings. It cannot delete,
rewrite or even touch the stored data.

The guiding rule for every detector: **a finding must be checkable.** Each one
carries the memories involved and the evidence that triggered it, and where the
evidence is weak the finding says so instead of pretending to be certain.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import (
    contradiction_context_overlap,
    contradiction_min_shared_tokens,
    low_confidence_threshold,
    near_duplicate_similarity,
    stale_after_days,
    vague_content_length,
    very_stale_after_days,
)
from app.schemas import HealthFinding, HealthReport, IssueType, Memory, Severity
from app.services.text import (
    PLACEHOLDER_PROJECTS,
    UNRELIABLE_SOURCES,
    context_tokens,
    contains_instruction_like_text,
    is_strong_value,
    normalize_text,
    overlap_coefficient,
    similarity,
    value_tokens,
)

ANALYZER = "deterministic-rules"

#: Categories whose statements can meaningfully disagree with each other.
#: A "failure" or "convention" is not a value claim, so it is left out.
CONTRADICTION_CATEGORIES = {"decision", "fact", "constraint"}

#: Categories where a missing confidence value is worth reporting. A fact or a
#: convention is not usually scored, so demanding one would be noise.
CONFIDENCE_RELEVANT_CATEGORIES = {"decision", "constraint"}

#: Source names that signal a reference nobody can go and check.
WEAK_SOURCE_MARKERS = ("old", "wiki", "draft", "legacy", "deprecated", "scratch")

#: Findings are ordered by severity, so the worst problem is first.
_SEVERITY_ORDER = {
    Severity.HIGH: 0,
    Severity.MEDIUM: 1,
    Severity.LOW: 2,
    Severity.INFO: 3,
}


def _finding_id(issue_type: IssueType, memory_ids: list[str]) -> str:
    """Stable, readable identifier so a finding can be referenced in a report."""
    key = ",".join(sorted(memory_ids)[:2])
    return f"{issue_type.value}:{key}"


def _make(
    issue_type: IssueType,
    severity: Severity,
    title: str,
    explanation: str,
    evidence: list[str],
    memory_ids: list[str],
    suggested_action: str,
    uncertainty: str | None = None,
) -> HealthFinding:
    return HealthFinding(
        id=_finding_id(issue_type, memory_ids),
        issue_type=issue_type,
        severity=severity,
        title=title,
        explanation=explanation,
        evidence=evidence,
        memory_ids=memory_ids,
        suggested_action=suggested_action,
        uncertainty=uncertainty,
    )


def _describe(memory: Memory) -> str:
    return f"[{memory.id}] ({memory.project}/{memory.category.value}) {memory.content}"


def _age_days(memory: Memory, now: datetime) -> int | None:
    created = memory.created_at
    if created is None:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = now - created
    return delta.days


# --- detectors --------------------------------------------------------------


def find_exact_duplicates(memories: list[Memory]) -> list[HealthFinding]:
    """Identical statements, once punctuation and case are ignored.

    Scoped to a project on purpose: the same convention stated in two projects
    is legitimate, not a duplicate.
    """
    buckets: dict[tuple[str, str], list[Memory]] = {}
    for memory in memories:
        key = (memory.project, normalize_text(memory.content))
        buckets.setdefault(key, []).append(memory)

    findings: list[HealthFinding] = []
    for (_, _), group in buckets.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda memory: memory.id)
        for index, memory in enumerate(ordered):
            for other in ordered[index + 1 :]:
                findings.append(
                    _make(
                        IssueType.EXACT_DUPLICATE,
                        Severity.MEDIUM,
                        "Exact duplicate memory",
                        (
                            "These two memories are identical once case, punctuation "
                            "and spacing are ignored. Only one needs to be kept; the "
                            "other adds noise to retrieval."
                        ),
                        [_describe(memory), _describe(other)],
                        [memory.id, other.id],
                        (
                            "Review both, keep the one with the better source, and "
                            "delete the other. DevMemory will not do this for you."
                        ),
                    )
                )
    return findings


def _contradiction_pairs(
    memories: list[Memory],
) -> list[tuple[Memory, Memory, set[str], set[str]]]:
    """Pairs that disagree about a value while talking about the same thing.

    Returns the pair plus the two sets of values that disagree.
    """
    pairs: list[tuple[Memory, Memory, set[str], set[str]]] = []
    overlap_threshold = contradiction_context_overlap()
    min_shared = contradiction_min_shared_tokens()

    for index, left in enumerate(memories):
        if left.category.value not in CONTRADICTION_CATEGORIES:
            continue
        for right in memories[index + 1 :]:
            if right.category.value not in CONTRADICTION_CATEGORIES:
                continue
            # Different projects may legitimately use different technology.
            if left.project != right.project:
                continue

            left_context = context_tokens(left.content)
            right_context = context_tokens(right.content)
            shared = left_context & right_context
            if len(shared) < min_shared:
                continue
            if overlap_coefficient(left_context, right_context) < overlap_threshold:
                continue

            left_values = value_tokens(left.content)
            right_values = value_tokens(right.content)
            only_left = {
                value for value in left_values - right_values if is_strong_value(value)
            }
            only_right = {
                value for value in right_values - left_values if is_strong_value(value)
            }
            if not only_left or not only_right:
                # They agree, or the difference is not a value claim.
                continue

            pairs.append((left, right, only_left, only_right))
    return pairs


def find_contradictions(memories: list[Memory]) -> list[HealthFinding]:
    """Statements that look like they cannot both be true.

    Reported as *potential* contradictions. Two memories can disagree while
    both being correct — different services, different environments, or a
    decision that changed over time. The finding says so.

    Pairs are grouped by which values disagree, so three memories where two
    are duplicates of each other produce one finding listing all three, not
    two findings describing the same underlying problem.
    """
    groups: dict[tuple[str, frozenset[frozenset[str]]], list[tuple[Memory, Memory, set[str], set[str]]]] = {}

    for left, right, only_left, only_right in _contradiction_pairs(memories):
        # The direction of the disagreement must not affect the grouping key.
        values = frozenset({frozenset(only_left), frozenset(only_right)})
        key = (left.project, values)
        groups.setdefault(key, []).append((left, right, only_left, only_right))

    findings: list[HealthFinding] = []
    for (project, values), pairs in groups.items():
        involved: dict[str, Memory] = {}
        for left, right, _, _ in pairs:
            involved[left.id] = left
            involved[right.id] = right

        ordered = [involved[memory_id] for memory_id in sorted(involved)]
        difference = " vs ".join(
            "{" + ", ".join(sorted(value)) + "}" for value in sorted(values, key=sorted)
        )

        findings.append(
            _make(
                IssueType.POTENTIAL_CONTRADICTION,
                Severity.MEDIUM,
                "Potential contradiction between memories",
                (
                    f"These {len(ordered)} memories in project '{project}' describe "
                    f"the same subject but name different values ({difference}). "
                    "They cannot all describe the current state of the project, but "
                    "only some of them are wrong."
                ),
                [_describe(memory) for memory in ordered]
                + [f"Differing values: {difference}"],
                [memory.id for memory in ordered],
                (
                    "Confirm which one reflects the current state, then mark the "
                    "outdated ones as superseded and point them at the current one."
                ),
                (
                    "This is a candidate, not a verdict. The memories may describe "
                    "different services, different environments, or different points "
                    "in time. Check the sources and dates before acting."
                ),
            )
        )
    return findings


def find_near_duplicates(memories: list[Memory]) -> list[HealthFinding]:
    """Same statement, different wording.

    Pairs already reported as contradictions are excluded: a pair that disagrees
    about a value is a contradiction, not a near-duplicate, and reporting both
    would double-count one problem.
    """
    contradicted = {
        frozenset({left.id, right.id})
        for left, right, _, _ in _contradiction_pairs(memories)
    }
    threshold = near_duplicate_similarity()

    findings: list[HealthFinding] = []
    for index, left in enumerate(memories):
        for right in memories[index + 1 :]:
            if left.project != right.project:
                continue
            if frozenset({left.id, right.id}) in contradicted:
                continue
            if normalize_text(left.content) == normalize_text(right.content):
                continue  # already reported as an exact duplicate

            score = similarity(left.content, right.content)
            if score < threshold:
                continue

            left_context = context_tokens(left.content)
            right_context = context_tokens(right.content)
            if overlap_coefficient(left_context, right_context) < 0.5:
                continue

            findings.append(
                _make(
                    IssueType.NEAR_DUPLICATE,
                    Severity.LOW,
                    "Near-duplicate memory",
                    (
                        "These two memories say substantially the same thing in "
                        f"different words (similarity {score:.2f}, threshold "
                        f"{threshold:.2f}). They do not contradict each other, so "
                        "both are probably correct, but they split the signal a "
                        "retriever has to work with."
                    ),
                    [
                        _describe(left),
                        _describe(right),
                        f"Similarity: {score:.2f}",
                    ],
                    [left.id, right.id],
                    (
                        "Consider merging them into one memory that states the "
                        "shared fact once, keeping the richer wording."
                    ),
                )
            )
    return findings


def find_stale(memories: list[Memory], now: datetime) -> list[HealthFinding]:
    """Memories old enough that they may no longer reflect the project.

    Age is the only available signal. There is no review metadata in the
    schema, so every stale finding says so rather than asserting the memory is
    wrong.
    """
    findings: list[HealthFinding] = []
    stale_after = stale_after_days()
    very_stale_after = very_stale_after_days()

    for memory in memories:
        if memory.status.value == "superseded":
            continue  # already retired, that is not staleness

        age = _age_days(memory, now)
        if age is None or age <= stale_after:
            continue

        severity = Severity.LOW
        if age > very_stale_after:
            severity = Severity.MEDIUM
        if memory.category.value == "decision":
            severity = (
                Severity.HIGH if age > very_stale_after else Severity.MEDIUM
            )
        if (
            memory.confidence is not None
            and memory.confidence <= low_confidence_threshold()
        ):
            severity = Severity.HIGH

        findings.append(
            _make(
                IssueType.POTENTIALLY_STALE,
                severity,
                "Memory may be out of date",
                (
                    f"This memory was recorded {age} days ago and has not been "
                    "updated since. Decisions and constraints are the ones most "
                    "likely to have been overtaken by later changes."
                ),
                [
                    _describe(memory),
                    f"Created: {memory.created_at.isoformat()}",
                    f"Age: {age} days",
                    f"Confidence: {memory.confidence if memory.confidence is not None else 'not recorded'}",
                ],
                [memory.id],
                (
                    "Check the source and confirm the statement still holds, then "
                    "either refresh it or mark it superseded."
                ),
                (
                    "Age is the only signal available: this schema records no "
                    "review date or explicit validity flag, so the memory may well "
                    "still be correct."
                ),
            )
        )
    return findings


def find_superseded(memories: list[Memory]) -> list[HealthFinding]:
    """Retired decisions, reported so history stays visible.

    Not a problem in itself — this is the mechanism working. It is included at
    info level so a reader can see which decisions are no longer current.
    """
    findings: list[HealthFinding] = []
    for memory in memories:
        if memory.status.value != "superseded":
            continue
        findings.append(
            _make(
                IssueType.SUPERSEDED_MEMORY,
                Severity.INFO,
                "Memory has been superseded",
                (
                    "This decision was retired and replaced by a newer memory. The "
                    "original is kept on purpose: history explains why the current "
                    "decision is the current one."
                ),
                [
                    _describe(memory),
                    f"Replaced by: {memory.superseded_by}",
                ],
                [memory.id],
                (
                    "No action needed. Keep it: removing it would erase the "
                    "reasoning behind the decision that replaced it."
                ),
            )
        )
    return findings


def find_metadata_issues(memories: list[Memory]) -> list[HealthFinding]:
    """Memories whose metadata is missing, weak or suspicious."""
    findings: list[HealthFinding] = []
    weak_threshold = low_confidence_threshold()

    for memory in memories:
        if (
            memory.category.value in CONFIDENCE_RELEVANT_CATEGORIES
            and memory.confidence is None
        ):
            findings.append(
                _make(
                    IssueType.MISSING_CONFIDENCE,
                    Severity.LOW,
                    "No confidence recorded",
                    (
                        f"A {memory.category.value} memory with no confidence value. "
                        "A retrieval system has no way to weigh this memory against "
                        "a competing one."
                    ),
                    [
                        _describe(memory),
                        "confidence: not set",
                    ],
                    [memory.id],
                    "Record a confidence value, or add a note explaining why it is unknown.",
                )
            )

        if (
            memory.confidence is not None
            and memory.confidence <= weak_threshold
            and memory.category.value == "decision"
        ):
            findings.append(
                _make(
                    IssueType.LOW_CONFIDENCE,
                    Severity.MEDIUM,
                    "Decision recorded with low confidence",
                    (
                        f"This decision's own confidence value is {memory.confidence}, "
                        "which means the memory itself flags it as doubtful. A "
                        "decision an agent will act on should be settled."
                    ),
                    [
                        _describe(memory),
                        f"confidence: {memory.confidence}",
                    ],
                    [memory.id],
                    "Confirm the decision and raise the confidence, or retire it as superseded.",
                )
            )

        normalised_source = normalize_text(memory.source)
        source_tokens = set(normalised_source.split())
        unreliable = (
            normalised_source in UNRELIABLE_SOURCES
            or bool(source_tokens & UNRELIABLE_SOURCES)
            or any(marker in normalised_source for marker in WEAK_SOURCE_MARKERS)
        )
        if unreliable:
            findings.append(
                _make(
                    IssueType.UNRELIABLE_SOURCE,
                    Severity.MEDIUM,
                    "Memory has a source nobody can check",
                    (
                        "The source of this memory does not point at a document, "
                        "ticket or review that could be re-read. A memory that "
                        "cannot be traced back cannot be verified or corrected."
                    ),
                    [
                        _describe(memory),
                        f"source: {memory.source}",
                    ],
                    [memory.id],
                    "Replace the source with a reference someone else can open.",
                )
            )

        if memory.project.strip().lower() in PLACEHOLDER_PROJECTS:
            findings.append(
                _make(
                    IssueType.PLACEHOLDER_PROJECT,
                    Severity.MEDIUM,
                    "Memory is filed under a placeholder project",
                    (
                        "The project namespace is a placeholder, so this memory is "
                        "outside every real namespace. A retrieval query scoped to a "
                        "project will never reach it, and it cannot be excluded by "
                        "project either."
                    ),
                    [
                        _describe(memory),
                        f"project: {memory.project}",
                    ],
                    [memory.id],
                    "Move the memory into the project it actually belongs to.",
                )
            )

        if len(memory.content.strip()) < vague_content_length():
            findings.append(
                _make(
                    IssueType.VAGUE_CONTENT,
                    Severity.LOW,
                    "Memory content is too short to be useful",
                    (
                        "This memory is shorter than "
                        f"{vague_content_length()} characters, so it does not say "
                        "enough to be retrieved confidently or acted on safely."
                    ),
                    [
                        _describe(memory),
                        f"length: {len(memory.content.strip())} characters",
                    ],
                    [memory.id],
                    "Expand the content, or delete the memory if it carried no information.",
                )
            )

        if contains_instruction_like_text(memory.content):
            findings.append(
                _make(
                    IssueType.SUSPICIOUS_CONTENT,
                    Severity.HIGH,
                    "Memory contains instruction-like text",
                    (
                        "This memory reads like a command rather than a record of "
                        "project knowledge. Memories are data: whatever wrote this "
                        "should not be able to steer what an agent does with it."
                    ),
                    [
                        _describe(memory),
                        "content contains instruction-like phrasing",
                    ],
                    [memory.id],
                    (
                        "Read it before trusting it, and treat it as untrusted text "
                        "rather than as a rule. DevMemory never acts on memory "
                        "content."
                    ),
                    (
                        "The match is on phrasing, not intent. This may be a "
                        "legitimate note that happens to contain words like "
                        "'ignore previous'."
                    ),
                )
            )

    return findings


LIMITATIONS = [
    "Duplicate and near-duplicate detection only compares memories within the same project.",
    "Contradiction detection is limited to decision, fact and constraint categories, and "
    "requires the two memories to share a recognisable subject.",
    "Staleness is inferred from age alone; the schema records no review date or validity flag.",
    "A contradiction is a candidate, not a verdict. Two memories may legitimately "
    "disagree because they describe different services or different points in time.",
    "All findings come from deterministic rules. Nothing here has been reviewed by a model, "
    "so nothing here can be wrong in a way a language model would explain.",
]


def analyze(memories: list[Memory], now: datetime | None = None) -> HealthReport:
    """Run every detector over a collection of memories.

    Read-only: this function never modifies the memories it is given.
    """
    generated_at = now or datetime.now(timezone.utc)
    ordered = sorted(memories, key=lambda memory: memory.id)

    findings: list[HealthFinding] = []
    findings.extend(find_exact_duplicates(ordered))
    findings.extend(find_contradictions(ordered))
    findings.extend(find_near_duplicates(ordered))
    findings.extend(find_stale(ordered, generated_at))
    findings.extend(find_superseded(ordered))
    findings.extend(find_metadata_issues(ordered))

    findings.sort(
        key=lambda finding: (
            _SEVERITY_ORDER[finding.severity],
            finding.issue_type.value,
            finding.id,
        )
    )

    summary: dict[str, int] = {}
    for finding in findings:
        key = finding.issue_type.value
        summary[key] = summary.get(key, 0) + 1

    return HealthReport(
        generated_at=generated_at,
        analyzer=ANALYZER,
        total_memories=len(ordered),
        projects=sorted({memory.project for memory in ordered}),
        summary=summary,
        findings=findings,
        limitations=LIMITATIONS,
    )
