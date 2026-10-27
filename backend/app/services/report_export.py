"""Render the inspector report as Markdown.

The export is a shareable artefact, so it carries its own context: what was
measured, with which provider, against which benchmark, and when. A report
without that is a set of numbers a reader cannot evaluate.

Rendering lives apart from the report builder so the numbers are never
re-derived here — this module only formats what ``report.build`` produced.
"""

from __future__ import annotations

from app.schemas import InspectorReport

SEVERITY_ORDER = ["high", "medium", "low", "info"]


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_(none)_\n"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def _metric(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def to_markdown(report: InspectorReport) -> str:
    inventory = report.inventory
    health = report.health
    keyword = report.retrieval.keyword
    semantic = report.retrieval.semantic
    context = report.context

    scope = report.scope_project or "all projects"
    lines: list[str] = []

    lines.append("# DevMemory inspector report")
    lines.append("")
    lines.append(f"- **Generated:** {report.generated_at.isoformat()}")
    lines.append(f"- **Scope:** {scope}")
    lines.append(f"- **Memories inspected:** {inventory.total}")
    lines.append("")

    # --- what was measured ---------------------------------------------------
    lines.append("## How this was measured")
    lines.append("")
    lines.append(
        "Every number below was computed from the stored memories and the "
        "version-controlled benchmark at the time shown."
    )
    lines.append("")
    lines.append(
        _table(
            ["Aspect", "Value"],
            [
                ["Retrieval strategy", f"`{context.retrieval_strategy}`"],
                ["Benchmark version", str(context.benchmark_version)],
                ["Benchmark queries", str(context.benchmark_query_count)],
                ["Cut-off k", str(context.benchmark_k)],
                [
                    "Embedding provider",
                    f"`{context.embedding_provider}` / `{context.embedding_model}`"
                    + (
                        " (captures meaning)"
                        if context.embedding_captures_meaning
                        else " (**surface form only — not a semantic model**) "
                    ),
                ],
                [
                    "Embeddings indexed",
                    f"{context.embeddings_indexed} of {inventory.total}"
                    + (
                        f" ({context.embeddings_stale} stale)"
                        if context.embeddings_stale
                        else ""
                    ),
                ],
                [
                    "AI analysis",
                    f"consulted (`{context.ai_model}`)"
                    if context.ai_consulted
                    else f"not consulted — {context.ai_unavailable_reason or 'unavailable'}",
                ],
            ],
        )
    )

    # --- inventory -----------------------------------------------------------
    lines.append("## Memory inventory")
    lines.append("")
    lines.append(
        _table(
            ["Project", "Memories"],
            [[name, str(count)] for name, count in inventory.by_project.items()],
        )
    )
    lines.append(
        _table(
            ["Category", "Memories"],
            [[name, str(count)] for name, count in inventory.by_category.items()],
        )
    )
    lines.append(
        _table(
            ["Status", "Memories"],
            [[name, str(count)] for name, count in inventory.by_status.items()],
        )
    )
    lines.append(
        f"Confidence recorded on {inventory.with_confidence} of "
        f"{inventory.total} memories."
    )
    lines.append("")

    # --- deterministic findings ---------------------------------------------
    lines.append("## Deterministic findings")
    lines.append("")
    lines.append(
        f"{len(health.findings)} finding(s) from rule-based analysis "
        f"(`{health.analyzer}`). No language model was involved in this section."
    )
    lines.append("")

    for severity in SEVERITY_ORDER:
        group = [
            finding for finding in health.findings if finding.severity.value == severity
        ]
        if not group:
            continue
        lines.append(f"### {severity.capitalize()} ({len(group)})")
        lines.append("")
        for finding in group:
            lines.append(f"**{finding.title}** — `{finding.issue_type.value}`")
            lines.append("")
            lines.append(finding.explanation)
            lines.append("")
            if finding.evidence:
                lines.append("Evidence:")
                for item in finding.evidence:
                    lines.append(f"- {item}")
                lines.append("")
            if finding.uncertainty:
                lines.append(f"> Uncertainty: {finding.uncertainty}")
                lines.append("")
            lines.append(f"Suggested action: {finding.suggested_action}")
            lines.append("")
            lines.append(f"Memories: `{'`, `'.join(finding.memory_ids)}`")
            lines.append("")

    # --- AI findings ---------------------------------------------------------
    lines.append("## AI-assisted findings")
    lines.append("")
    if report.ai.consulted:
        lines.append(
            f"**Model-generated.** {len(report.ai.findings)} suggestion(s) from "
            f"`{report.ai.model}`. These are suggestions to check, not assertions, "
            "and nothing was applied."
        )
        lines.append("")
        if not report.ai.findings:
            lines.append("_The model reported no additional problems._")
            lines.append("")
        for finding in report.ai.findings:
            lines.append(
                f"**{finding.title}** — `{finding.issue_type.value}` "
                f"(severity {finding.severity.value}, model uncertainty "
                f"{finding.uncertainty})"
            )
            lines.append("")
            lines.append(finding.explanation)
            lines.append("")
            for item in finding.evidence:
                lines.append(f"- _{item}_")
            if finding.evidence:
                lines.append("")
            lines.append(f"Suggested action: {finding.suggested_action}")
            lines.append("")
        if report.ai.rejected:
            lines.append(f"Rejected suggestions ({len(report.ai.rejected)}):")
            for item in report.ai.rejected:
                lines.append(f"- {item}")
            lines.append("")
    else:
        lines.append(
            "No language model was consulted, so paraphrase-level duplicates and "
            "differently-worded contradictions were **not** checked. The "
            "deterministic section above is unaffected."
        )
        lines.append("")

    # --- retrieval -----------------------------------------------------------
    lines.append("## Retrieval benchmark")
    lines.append("")
    if semantic is not None:
        rows = [
            [
                metric,
                _metric(getattr(keyword.summary, attribute)),
                _metric(getattr(semantic.summary, attribute)),
            ]
            for metric, attribute in (
                ("Precision@k", "mean_precision_at_k"),
                ("Recall@k", "mean_recall_at_k"),
                ("MRR", "mrr"),
                ("Memories missed", "total_missed"),
                ("Irrelevant returned", "total_irrelevant_retrieved"),
            )
        ]
        lines.append(_table(["Metric", "Keyword", "Semantic"], rows))
    else:
        lines.append(
            _table(
                ["Metric", "Keyword"],
                [
                    [metric, _metric(getattr(keyword.summary, attribute))]
                    for metric, attribute in (
                        ("Precision@k", "mean_precision_at_k"),
                        ("Recall@k", "mean_recall_at_k"),
                        ("MRR", "mrr"),
                        ("Memories missed", "total_missed"),
                        ("Irrelevant returned", "total_irrelevant_retrieved"),
                    )
                ],
            )
        )
        lines.append(
            "Semantic results are absent because no semantic benchmark was run in "
            "this report."
        )
        lines.append("")

    lines.append(
        f"Scored {keyword.summary.valid_queries} of "
        f"{keyword.summary.query_count} queries at k={keyword.summary.k}."
    )
    lines.append("")

    if report.retrieval.missed_examples:
        lines.append("### Retrieval failures")
        lines.append("")
        for example in report.retrieval.missed_examples:
            lines.append(f"- **{example.query_id}**: “{example.query}”")
            for item in example.missed:
                lines.append(f"  - missed: {item}")
        lines.append("")

    # --- recommendations -----------------------------------------------------
    lines.append("## Recommended next actions")
    lines.append("")
    if not report.recommendations:
        lines.append("_No recommendations._")
        lines.append("")
    else:
        for index, item in enumerate(report.recommendations, start=1):
            lines.append(f"{index}. **[{item.priority}] {item.title}**")
            lines.append(f"   {item.rationale}")
            lines.append("")

    # --- limitations ---------------------------------------------------------
    lines.append("## What this report does not tell you")
    lines.append("")
    for note in report.notes:
        lines.append(f"- {note}")
    lines.append("")
    for limitation in health.limitations:
        lines.append(f"- {limitation}")
    lines.append("")

    return "\n".join(lines)