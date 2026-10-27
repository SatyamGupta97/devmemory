import { useState } from "react";
import { describeError, retrieveMemories } from "../api/client";
import type { RetrievalResult } from "../types";

interface Props {
  /** The project filter currently applied to the memory list. */
  projectFilter: string;
  onSelectMemory: (id: string) => void;
}

const EXAMPLE_QUERY = "Add caching to the user service.";

export function RetrievalPanel({ projectFilter, onSelectMemory }: Props) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<RetrievalResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (task: string) => {
    setLoading(true);
    setError(null);
    try {
      setResult(
        await retrieveMemories({
          query: task,
          project: projectFilter || undefined,
        }),
      );
    } catch (caught) {
      setResult(null);
      setError(describeError(caught));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="retrieval" aria-label="Retrieval playground">
      <h2 className="form-heading">Retrieval playground</h2>
      <p className="hint">
        Describe a coding task. Memories are ranked by keyword relevance, and every
        score shows which terms produced it.
      </p>

      <form
        className="retrieval-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim()) void run(query);
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
              void run(EXAMPLE_QUERY);
            }}
          >
            Use the example
          </button>
        </div>
      </form>

      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="retrieval-result">
          <p className="hint">
            <strong>{result.returned}</strong> of {result.considered} memories
            returned for “{result.query}” using{" "}
            <code>{result.strategy}</code>
            {result.project ? ` in ${result.project}` : " across all projects"}.
          </p>

          {result.matches.length === 0 ? (
            <div className="placeholder">
              <p>No memory shares a word with this task.</p>
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