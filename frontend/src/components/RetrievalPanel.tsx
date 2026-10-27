import { useCallback, useEffect, useState } from "react";
import {
  describeError,
  getEmbeddingStatus,
  indexEmbeddings,
  retrieveMemories,
} from "../api/client";
import type { EmbeddingStatus, RetrievalResult, RetrievalStrategy } from "../types";

interface Props {
  /** The project filter currently applied to the memory list. */
  projectFilter: string;
  onSelectMemory: (id: string) => void;
}

const EXAMPLE_QUERY = "Add caching to the user service.";

export function RetrievalPanel({ projectFilter, onSelectMemory }: Props) {
  const [query, setQuery] = useState("");
  const [strategy, setStrategy] = useState<RetrievalStrategy>("keyword");
  const [result, setResult] = useState<RetrievalResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [status, setStatus] = useState<EmbeddingStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [indexing, setIndexing] = useState(false);
  const [indexNotice, setIndexNotice] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await getEmbeddingStatus());
      setStatusError(null);
    } catch (caught) {
      // The status is supporting information: if it cannot be fetched, retrieval
      // still works and the panel simply does not claim to know the index state.
      setStatus(null);
      setStatusError(describeError(caught));
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const run = async (task: string, mode: RetrievalStrategy) => {
    setLoading(true);
    setError(null);
    try {
      setResult(
        await retrieveMemories({
          query: task,
          project: projectFilter || undefined,
          strategy: mode,
        }),
      );
    } catch (caught) {
      setResult(null);
      setError(describeError(caught));
    } finally {
      setLoading(false);
    }
  };

  const buildIndex = async (force: boolean) => {
    setIndexing(true);
    setIndexNotice(null);
    setError(null);
    try {
      const outcome = await indexEmbeddings({
        project: projectFilter || undefined,
        force,
      });
      setIndexNotice(
        outcome.failed > 0
          ? `Indexing failed: ${outcome.errors[0] ?? "unknown error"}`
          : `Indexed ${outcome.indexed}, skipped ${outcome.skipped} already current.`,
      );
      await loadStatus();
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setIndexing(false);
    }
  };

  const needsIndexing = status !== null && status.stale_memories > 0;

  return (
    <section className="retrieval" aria-label="Retrieval playground">
      <h2 className="form-heading">Retrieval playground</h2>
      <p className="hint">
        Describe a coding task. Memories are ranked by the chosen strategy, and
        every result says which one produced it.
      </p>

      <form
        className="retrieval-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim()) void run(query, strategy);
        }}
      >
        <label htmlFor="retrieval-query">Coding task</label>
        <input
          id="retrieval-query"
          value={query}
          maxLength={500}
          placeholder={EXAMPLE_QUERY}
          onChange={(event) => setQuery(event.target.value)}
        />

        <label htmlFor="retrieval-strategy">Strategy</label>
        <select
          id="retrieval-strategy"
          value={strategy}
          onChange={(event) => setStrategy(event.target.value as RetrievalStrategy)}
        >
          <option value="keyword">Keyword (BM25) — matches words</option>
          <option value="semantic">Semantic — matches vectors</option>
        </select>

        <div className="form-actions">
          <button
            type="submit"
            className="button button-primary"
            disabled={loading || query.trim() === ""}
          >
            {loading ? "Retrieving…" : "Retrieve"}
          </button>
          <button
            type="button"
            className="button"
            disabled={loading}
            onClick={() => {
              setQuery(EXAMPLE_QUERY);
              void run(EXAMPLE_QUERY, strategy);
            }}
          >
            Use the example
          </button>
        </div>
      </form>

      <div className="embedding-box">
        <h3 className="embedding-heading">Embedding index</h3>

        {statusError && (
          <p className="hint">
            Index status unavailable: {statusError}. Retrieval still works.
          </p>
        )}

        {status && (
          <>
            <p className="hint">
              Provider <code>{status.provider}</code> · model{" "}
              <code>{status.model}</code> · {status.dimensions} dimensions ·{" "}
              {status.indexed_memories} of {status.total_memories} memories indexed
              {status.stale_memories > 0 && (
                <> · <strong>{status.stale_memories} need indexing</strong></>
              )}
            </p>

            {!status.captures_meaning && (
              <p className="embedding-warning">
                This provider compares surface form, not meaning. A paraphrase with
                no shared words still scores zero. Set an embedding API key and
                model to switch to a hosted model.
              </p>
            )}

            <div className="form-actions">
              <button
                type="button"
                className="button"
                disabled={indexing}
                onClick={() => void buildIndex(false)}
              >
                {indexing ? "Indexing…" : "Index memories"}
              </button>
              <button
                type="button"
                className="button"
                disabled={indexing}
                onClick={() => void buildIndex(true)}
              >
                Re-index everything
              </button>
            </div>

            {indexNotice && <p className="hint">{indexNotice}</p>}
            {needsIndexing && (
              <p className="hint">
                Semantic retrieval will exclude memories without a current vector.
              </p>
            )}
          </>
        )}
      </div>

      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="retrieval-result">
          <p className="hint">
            <strong>{result.returned}</strong> of {result.considered} memories
            returned for “{result.query}” using <code>{result.strategy}</code>
            {result.project ? ` in ${result.project}` : " across all projects"}.
          </p>

          {result.matches.length === 0 ? (
            <div className="placeholder">
              <p>No memory is close enough to this task.</p>
              {result.unmatched_query_terms.length > 0 && (
                <p className="hint">
                  These query terms matched nothing:{" "}
                  {result.unmatched_query_terms.join(", ")}. Keyword search cannot
                  find a memory that means the same thing in different words — a
                  known limitation of this baseline.
                </p>
              )}
            </div>
          ) : (
            <ol className="match-list" aria-label="Ranked memories">
              {result.matches.map((match, index) => (
                <li className="match" key={match.memory.id}>
                  <div className="match-head">
                    <span className="match-rank">#{index + 1}</span>
                    <span className="match-score">
                      score {match.score.toFixed(3)}
                    </span>
                    <span className="badge badge-fact">{match.method}</span>
                    <span className="memory-card-project">
                      {match.memory.project}
                    </span>
                    <span className={`badge badge-${match.memory.category}`}>
                      {match.memory.category}
                    </span>
                    {match.memory.status === "superseded" && (
                      <span className="badge badge-superseded">superseded</span>
                    )}
                  </div>

                  <p className="match-content">{match.memory.content}</p>
                  <p className="match-explanation">{match.explanation}</p>

                  {match.matched_terms.length > 0 && (
                    <div className="match-terms">
                      {match.matched_terms.map((term) => (
                        <span className="term-chip" key={term.term}>
                          {term.term}
                          <span className="term-detail">
                            x{term.term_frequency} · {term.contribution.toFixed(2)}
                          </span>
                        </span>
                      ))}
                    </div>
                  )}

                  <button
                    type="button"
                    className="link"
                    onClick={() => onSelectMemory(match.memory.id)}
                  >
                    Open this memory
                  </button>
                </li>
              ))}
            </ol>
          )}

          {result.unmatched_query_terms.length > 0 && result.matches.length > 0 && (
            <p className="hint">
              Ignored terms that matched no memory:{" "}
              {result.unmatched_query_terms.join(", ")}.
            </p>
          )}

          <details className="health-limitations">
            <summary>What this ranking cannot tell you</summary>
            <ul>
              {result.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </section>
  );
}