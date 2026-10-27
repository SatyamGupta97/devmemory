import { useEffect, useState } from "react";
import {
  describeError,
  getAiStatus,
  runAiAnalysis,
} from "../api/client";
import type { AiAnalysisReport, AiStatus } from "../types";

interface Props {
  projectFilter: string;
}

const ISSUE_LABEL: Record<string, string> = {
  semantic_duplicate: "Possible semantic duplicate",
  contradiction: "Possible contradiction",
  misclassification: "Possible wrong category",
  merge_suggestion: "Merge suggestion",
};

/**
 * Model-assisted analysis.
 *
 * Three things this component is careful about:
 *
 * 1. It says plainly that these findings come from a model, not from rules.
 * 2. It shows the model's own uncertainty next to each finding, because that is
 *    part of the model's answer, not decoration.
 * 3. It shows rejected suggestions. Hiding them would make a broken or hostile
 *    response look like a clean one.
 */
export function AiInsights({ projectFilter }: Props) {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [report, setReport] = useState<AiAnalysisReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const next = await getAiStatus();
        if (!cancelled) setStatus(next);
      } catch {
        // Status is supporting information; the deterministic panel above still
        // works if this call fails.
        if (!cancelled) setStatus(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await runAiAnalysis(projectFilter || undefined));
    } catch (caught) {
      setReport(null);
      setError(describeError(caught));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="ai" aria-label="AI-assisted analysis">
      <h3 className="embedding-heading">AI-assisted analysis</h3>

      <p className="hint">
        A language model looks for meaning that rules miss: paraphrase duplicates,
        contradictions phrased differently, and categories that do not fit. Every
        suggestion must be checked by a human — nothing is applied automatically.
      </p>

      {status && !status.available && (
        <p className="hint">
          Not configured{status.reason ? `: ${status.reason}` : "."} The
          deterministic checks above work without it.
        </p>
      )}

      {status?.available && (
        <div className="form-actions">
          <button
            type="button"
            className="button"
            onClick={() => void run()}
            disabled={loading}
          >
            {loading ? "Analysing…" : "Run AI analysis"}
          </button>
          <span className="ai-model">
            {status.provider} · <code>{status.model}</code>
          </span>
        </div>
      )}

      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}

      {report && (
        <div className="ai-report">
          <p className="ai-disclaimer">
            <strong>Model-generated.</strong> {report.findings.length} suggestion
            {report.findings.length === 1 ? "" : "s"} from{" "}
            <code>{report.model}</code> across {report.analyzed_memories} memories.
            Nothing was changed.
          </p>

          {report.findings.length === 0 && (
            <p className="hint">The model found nothing beyond the rule-based checks.</p>
          )}

          {report.findings.map((finding) => (
            <article className="ai-finding" key={finding.id}>
              <div className="finding-head">
                <span className={`severity severity-${finding.severity}`}>
                  {finding.severity}
                </span>
                <span className="badge badge-fact">model</span>
                <span className="finding-type">
                  {ISSUE_LABEL[finding.issue_type] ?? finding.issue_type}
                </span>
              </div>

              <h4 className="finding-title">{finding.title}</h4>
              <p className="finding-explanation">{finding.explanation}</p>

              {finding.evidence.length > 0 && (
                <ul className="ai-evidence">
                  {finding.evidence.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}

              <p className="finding-uncertainty">
                <strong>Model's uncertainty:</strong> {finding.uncertainty}
              </p>

              <p className="finding-action">
                <strong>Suggested action:</strong> {finding.suggested_action}
              </p>

              <p className="hint mono ai-ids">
                memories: {finding.memory_ids.join(", ")}
              </p>
            </article>
          ))}

          {report.rejected.length > 0 && (
            <details className="health-limitations ai-rejected">
              <summary>
                Rejected suggestions ({report.rejected.length})
              </summary>
              <p className="hint">
                These were discarded because they failed validation. A suggestion
                that names a memory which was not provided is not partially
                trustworthy.
              </p>
              <ul>
                {report.rejected.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </details>
          )}

          {report.excluded_memories.length > 0 && (
            <p className="hint">
              {report.excluded_memories.length} memory/memories were withheld from the
              prompt because their content reads like instructions to the model.
            </p>
          )}

          <details className="health-limitations">
            <summary>About this analysis</summary>
            <ul>
              {report.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </section>
  );
}