import type { HealthFinding, HealthReport } from "../types";
import { AiInsights } from "./AiInsights";

interface Props {
  report: HealthReport;
  onSelectMemory: (id: string) => void;
  projectFilter: string;
}

const SEVERITY_LABEL: Record<HealthFinding["severity"], string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

const ISSUE_LABEL: Record<string, string> = {
  exact_duplicate: "Exact duplicate",
  near_duplicate: "Near-duplicate",
  potential_contradiction: "Potential contradiction",
  potentially_stale: "Potentially stale",
  superseded_memory: "Superseded",
  missing_confidence: "Missing confidence",
  low_confidence: "Low confidence",
  unreliable_source: "Unreliable source",
  placeholder_project: "Placeholder project",
  vague_content: "Vague content",
  suspicious_content: "Suspicious content",
};

function FindingCard({
  finding,
  onSelectMemory,
}: {
  finding: HealthFinding;
  onSelectMemory: (id: string) => void;
}) {
  return (
    <li className="finding">
      <div className="finding-head">
        <span className={`severity severity-${finding.severity}`}>
          {SEVERITY_LABEL[finding.severity]}
        </span>
        <span className="finding-type">
          {ISSUE_LABEL[finding.issue_type] ?? finding.issue_type}
        </span>
      </div>

      <h3 className="finding-title">{finding.title}</h3>
      <p className="finding-explanation">{finding.explanation}</p>

      <details className="finding-evidence">
        <summary>Evidence ({finding.evidence.length})</summary>
        <ul>
          {finding.evidence.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>

      {finding.uncertainty && (
        <p className="finding-uncertainty">
          <strong>Uncertainty:</strong> {finding.uncertainty}
        </p>
      )}

      <p className="finding-action">
        <strong>Suggested action:</strong> {finding.suggested_action}
      </p>

      <div className="finding-ids">
        <span>Affected memories:</span>
        {finding.memory_ids.map((id) => (
          <button
            key={id}
            type="button"
            className="link"
            onClick={() => onSelectMemory(id)}
          >
            {id.slice(0, 8)}
          </button>
        ))}
      </div>
    </li>
  );
}

export function HealthPanel({ report, onSelectMemory, projectFilter }: Props) {
  const summaryEntries = Object.entries(report.summary);

  return (
    <section className="health" aria-label="Memory health check">
      <div className="health-head">
        <span className="health-analyzer">
          Analyzer: <code>{report.analyzer}</code> — no language model was used.
        </span>
      </div>

      <p className="hint">
        {report.total_memories} memories checked across{" "}
        {report.projects.length} project{report.projects.length === 1 ? "" : "s"}.
        Nothing was changed: every finding is a suggestion for you to act on.
      </p>

      {report.findings.length === 0 ? (
        <p className="placeholder">
          {report.total_memories === 0
            ? "Nothing to check yet. Import memories and run this again."
            : "No problems found. Either the collection is clean, or the rules below do not cover what is wrong with it."}
        </p>
      ) : (
        <>
          <ul className="health-summary" aria-label="Findings by type">
            {summaryEntries.map(([type, count]) => (
              <li key={type}>
                <span className="health-summary-count">{count}</span>
                <span className="health-summary-label">
                  {ISSUE_LABEL[type] ?? type}
                </span>
              </li>
            ))}
          </ul>

          <ul className="finding-list" aria-label="Findings">
            {report.findings.map((finding) => (
              <FindingCard
                key={finding.id}
                finding={finding}
                onSelectMemory={onSelectMemory}
              />
            ))}
          </ul>
        </>
      )}

      {report.limitations.length > 0 && (
        <details className="health-limitations">
          <summary>What this check cannot tell you</summary>
          <ul>
            {report.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </details>
      )}

      <AiInsights projectFilter={projectFilter} />
    </section>
  );
}
