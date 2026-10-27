import { useCallback, useEffect, useState } from "react";
import { describeError, getBenchmark, runBenchmark } from "../api/client";
import type {
  BenchmarkDefinition,
  BenchmarkReport,
  RetrievalStrategy,
} from "../types";

interface Props {
  onClose: () => void;
}

function pct(value: number | null): string {
  return value === null ? "—" : value.toFixed(3);
}

function summaryRows(report: BenchmarkReport): Array<[string, string]> {
  const summary = report.summary;
  return [
    ["Precision@k", pct(summary.mean_precision_at_k)],
    ["Recall@k", pct(summary.mean_recall_at_k)],
    ["MRR", pct(summary.mrr)],
    ["Queries scored", `${summary.valid_queries} of ${summary.query_count}`],
    ["Memories missed", String(summary.total_missed)],
    ["Irrelevant returned", String(summary.total_irrelevant_retrieved)],
  ];
}

export function BenchmarkPanel({ onClose }: Props) {
  const [definition, setDefinition] = useState<BenchmarkDefinition | null>(null);
  const [reports, setReports] = useState<Partial<Record<RetrievalStrategy, BenchmarkReport>>>(
    {},
  );
  const [loading, setLoading] = useState<RetrievalStrategy | "both" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDefinition = useCallback(async () => {
    try {
      setDefinition(await getBenchmark());
    } catch (caught) {
      setError(describeError(caught));
    }
  }, []);

  useEffect(() => {
    void loadDefinition();
  }, [loadDefinition]);

  const run = async (strategy: RetrievalStrategy) => {
    setLoading(strategy);
    setError(null);
    try {
      const report = await runBenchmark({ strategy });
      setReports((current) => ({ ...current, [strategy]: report }));
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setLoading(null);
    }
  };

  const runBoth = async () => {
    setLoading("both");
    setError(null);
    try {
      const keyword = await runBenchmark({ strategy: "keyword" });
      const next: Partial<Record<RetrievalStrategy, BenchmarkReport>> = {
        keyword,
      };
      // Semantic needs an index; if it is missing, keep the keyword result and
      // report why the comparison is incomplete rather than losing both.
      try {
        next.semantic = await runBenchmark({ strategy: "semantic" });
        setError(null);
      } catch (caught) {
        setError(`Semantic strategy unavailable: ${describeError(caught)}`);
      }
      setReports((current) => ({ ...current, ...next }));
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setLoading(null);
    }
  };

  const keyword = reports.keyword;
  const semantic = reports.semantic;
  const compared = keyword && semantic;

  return (
    <section className="benchmark" aria-label="Retrieval benchmark">
      <div className="health-head">
        <h2 className="form-heading">Retrieval benchmark</h2>
        <button type="button" className="link" onClick={onClose}>
          Close
        </button>
      </div>

      {definition && (
        <p className="hint">
          {definition.queries.length} version-controlled queries, cut-off k=
          {definition.default_k}. Ground truth is expected memory content, matched by a
          content key so it survives re-importing.
        </p>
      )}

      <div className="form-actions">
        <button
          type="button"
          className="button button-primary"
          disabled={loading !== null}
          onClick={() => void runBoth()}
        >
          {loading === "both" ? "Running…" : "Compare keyword vs semantic"}
        </button>
        <button
          type="button"
          className="button"
          disabled={loading !== null}
          onClick={() => void run("keyword")}
        >
          {loading === "keyword" ? "Running…" : "Run keyword"}
        </button>
        <button
          type="button"
          className="button"
          disabled={loading !== null}
          onClick={() => void run("semantic")}
        >
          {loading === "semantic" ? "Running…" : "Run semantic"}
        </button>
      </div>

      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}

      {!keyword && !semantic && !error && (
        <p className="placeholder">
          Run the benchmark to measure retrieval quality. Without it, a ranking can
          only be admired, not evaluated.
        </p>
      )}

      {compared && (
        <div className="benchmark-compare">
          <h3 className="embedding-heading">Measured comparison</h3>
          <div className="compare-grid">
            <div className="compare-column">
              <h4>Keyword (BM25)</h4>
              <dl>
                {summaryRows(keyword).map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="compare-column">
              <h4>Semantic (vectors)</h4>
              <dl>
                {summaryRows(semantic).map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </div>
      )}

      {!compared && keyword && (
        <div className="benchmark-single">
          <dl className="detail-grid">
            {summaryRows(keyword).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {keyword && (
        <table className="benchmark-table">
          <caption>
            Per-query outcomes{compared ? " for both strategies" : " for keyword"}
          </caption>
          <thead>
            <tr>
              <th scope="col">Query</th>
              <th scope="col">Type</th>
              <th scope="col">P@k</th>
              <th scope="col">R@k</th>
              <th scope="col">RR</th>
              {compared && <th scope="col">P@k (sem)</th>}
              {compared && <th scope="col">R@k (sem)</th>}
              <th scope="col">Missed</th>
            </tr>
          </thead>
          <tbody>
            {keyword.cases.map((case_) => {
              const other = semantic?.cases.find(
                (item) => item.query_id === case_.query_id,
              );
              return (
                <tr key={case_.query_id} className={case_.valid ? undefined : "row-invalid"}>
                  <th scope="row">
                    <span className="mono">{case_.query_id}</span>
                    <span className="benchmark-query-text">{case_.query}</span>
                  </th>
                  <td>{case_.kind}</td>
                  <td>{case_.precision_at_k.toFixed(2)}</td>
                  <td>{pct(case_.recall_at_k)}</td>
                  <td>{pct(case_.reciprocal_rank)}</td>
                  {compared && <td>{other ? other.precision_at_k.toFixed(2) : "—"}</td>}
                  {compared && <td>{other ? pct(other.recall_at_k) : "—"}</td>}
                  <td>
                    {case_.missed.length === 0 ? (
                      "—"
                    ) : (
                      <ul className="missed-list">
                        {case_.missed.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {(keyword ?? semantic) && (
        <details className="health-limitations">
          <summary>What these numbers do and do not prove</summary>
          <ul>
            {(keyword ?? semantic)!.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}