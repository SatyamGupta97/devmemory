import { useCallback, useEffect, useState } from "react";
import { describeError, getReport, reportExportUrl } from "../api/client";
import type { InspectorReport } from "../types";

interface Props {
  projectFilter: string;
  onClose: () => void;
}

function pct(value: number | null): string {
  return value === null ? "—" : value.toFixed(3);
}

/**
 * The consolidated inspector report.
 *
 * Deliberately shows the measurement context *above* the numbers: a reader who
 * sees a recall figure without knowing it came from ten queries over a
 * surface-form provider would draw the wrong conclusion.
 */
export function ReportPanel({ projectFilter, onClose }: Props) {
  const [report, setReport] = useState<InspectorReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await getReport(projectFilter || undefined));
    } catch (caught) {
      setReport(null);
      setError(describeError(caught));
    } finally {
      setLoading(false);
    }
  }, [projectFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !report) {
    return (
      <section className="report" aria-label="Inspector report">
        <p className="placeholder" role="status">
          Building the report…
        </p>
      </section>
    );
  }

  if (error && !report) {
    return (
      <section className="report" aria-label="Inspector report">
        <p className="field-error" role="alert">
          {error}
        </p>
        <button type="button" className="button" onClick={() => void load()}>
          Retry
        </button>
      </section>
    );
  }

  if (!report) return null;

  const { inventory, health, retrieval, context } = report;
  const keyword = retrieval.keyword.summary;
  const semantic = retrieval.semantic?.summary ?? null;

  return (
    <section className="report" aria-label="Inspector report">
      <div className="health-head">
        <h2 className="form-heading">Inspector report</h2>
        <button type="button" className="link" onClick={onClose}>
          Close
        </button>
      </div>

      <p className="hint">
        {inventory.total} memories in{" "}
        {report.scope_project ?? `${Object.keys(inventory.by_project).length} projects`}
        . Generated from stored data and the benchmark; nothing here is illustrative.
      </p>

      <div className="report-actions">
        <a className="button" href={reportExportUrl("markdown", projectFilter || undefined)}>
          Export Markdown
        </a>
        <a className="button" href={reportExportUrl("json", projectFilter || undefined)}>
          Export JSON
        </a>
      </div>

      <div className="report-context">
        <h3 className="embedding-heading">How this was measured</h3>
        <dl>
          <div>
            <dt>Benchmark</dt>
            <dd>
              v{context.benchmark_version} · {context.benchmark_query_count} queries ·
              k={context.benchmark_k}
            </dd>
          </div>
          <div>
            <dt>Embedding provider</dt>
            <dd>
              <code>{context.embedding_provider}</code> ·{" "}
              <code>{context.embedding_model}</code>
              {!context.embedding_captures_meaning && (
                <span className="context-warning"> surface form only</span>
              )}
            </dd>
          </div>
          <div>
            <dt>Vectors</dt>
            <dd>
              {context.embeddings_indexed} indexed
              {context.embeddings_stale > 0 && `, ${context.embeddings_stale} stale`}
            </dd>
          </div>
          <div>
            <dt>AI analysis</dt>
            <dd>
              {context.ai_consulted
                ? `consulted (${context.ai_model})`
                : "not consulted"}
            </dd>
          </div>
        </dl>
        {!context.embedding_captures_meaning && (
          <p className="embedding-warning">
            The retrieval numbers below come from a surface-form provider, not a
            semantic model. Treat them as a lower bound on what semantic retrieval
            can do.
          </p>
        )}
      </div>

      <div className="report-grid">
        <div>
          <h3 className="embedding-heading">Inventory</h3>
          <table className="benchmark-table">
            <caption>Memories by project</caption>
            <tbody>
              {Object.entries(inventory.by_project).map(([project, count]) => (
                <tr key={project}>
                  <th scope="row">{project}</th>
                  <td>{count}</td>
                </tr>
              ))}
              {Object.keys(inventory.by_project).length === 0 && (
                <tr>
                  <td colSpan={2}>No memories.</td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="hint">
            {inventory.with_confidence} of {inventory.total} have a confidence value.
          </p>
        </div>

        <div>
          <h3 className="embedding-heading">Findings</h3>
          <table className="benchmark-table">
            <caption>Deterministic checks</caption>
            <tbody>
              {Object.entries(health.summary).map(([type, count]) => (
                <tr key={type}>
                  <th scope="row">{type.replaceAll("_", " ")}</th>
                  <td>{count}</td>
                </tr>
              ))}
              {Object.keys(health.summary).length === 0 && (
                <tr>
                  <td colSpan={2}>No findings.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <h3 className="embedding-heading">Retrieval benchmark</h3>
      <table className="benchmark-table">
        <caption>
          Measured at k={keyword.k}; {keyword.valid_queries} of {keyword.query_count}{" "}
          queries scored
        </caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col">Keyword</th>
            <th scope="col">Semantic</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Precision@k</th>
            <td>{keyword.mean_precision_at_k.toFixed(3)}</td>
            <td>{semantic ? semantic.mean_precision_at_k.toFixed(3) : "—"}</td>
          </tr>
          <tr>
            <th scope="row">Recall@k</th>
            <td>{pct(keyword.mean_recall_at_k)}</td>
            <td>{semantic ? pct(semantic.mean_recall_at_k) : "—"}</td>
          </tr>
          <tr>
            <th scope="row">MRR</th>
            <td>{pct(keyword.mrr)}</td>
            <td>{semantic ? pct(semantic.mrr) : "—"}</td>
          </tr>
          <tr>
            <th scope="row">Missed</th>
            <td>{keyword.total_missed}</td>
            <td>{semantic ? semantic.total_missed : "—"}</td>
          </tr>
        </tbody>
      </table>

      {retrieval.missed_examples.length > 0 && (
        <details className="health-limitations">
          <summary>
            Retrieval failures ({retrieval.missed_examples.length})
          </summary>
          <ul>
            {retrieval.missed_examples.map((example) => (
              <li key={example.query_id}>
                <strong>{example.query_id}</strong>: “{example.query}”
                <ul>
                  {example.missed.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </details>
      )}

      <h3 className="embedding-heading">Recommended next actions</h3>
      <ol className="recommendations">
        {report.recommendations.map((item) => (
          <li key={`${item.priority}-${item.title}`} className="recommendation">
            <div className="finding-head">
              <span className={`severity severity-${item.priority}`}>
                {item.priority}
              </span>
              <strong>{item.title}</strong>
            </div>
            <p className="finding-explanation">{item.rationale}</p>
            {item.related.length > 0 && (
              <p className="hint">
                Related findings: {item.related.length}
              </p>
            )}
          </li>
        ))}
      </ol>

      {report.ai.consulted && report.ai.findings.length > 0 && (
        <>
          <h3 className="embedding-heading">Model-generated findings</h3>
          <p className="ai-disclaimer">
            <strong>Model-generated.</strong> Provided by <code>{report.ai.model}</code>.
            Nothing was applied; verify each one.
          </p>
          <ul className="ai-evidence">
            {report.ai.findings.map((finding) => (
              <li key={finding.id}>
                {finding.title} — uncertainty {finding.uncertainty}
              </li>
            ))}
          </ul>
        </>
      )}

      <details className="health-limitations">
        <summary>What this report does not tell you</summary>
        <ul>
          {report.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
          {report.health.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}