import { useState } from "react";
import { CATEGORIES, type Memory, type MemoryCategory } from "../types";

interface Props {
  /** Present when editing; absent when creating. */
  initial?: Memory;
  busy: boolean;
  onSubmit: (values: {
    content: string;
    category: MemoryCategory;
    source: string;
    project: string;
    confidence: number | null;
  }) => void;
  onCancel?: () => void;
}

export function MemoryForm({ initial, busy, onSubmit, onCancel }: Props) {
  const [content, setContent] = useState(initial?.content ?? "");
  const [category, setCategory] = useState<MemoryCategory>(
    initial?.category ?? "decision",
  );
  const [source, setSource] = useState(initial?.source ?? "");
  const [project, setProject] = useState(initial?.project ?? "");
  const [confidence, setConfidence] = useState(
    initial?.confidence === null || initial?.confidence === undefined
      ? ""
      : String(initial.confidence),
  );

  // Confidence is optional, so "" means "not set" rather than 0. Treating an
  // empty field as 0 would silently claim total uncertainty.
  const confidenceValue = confidence.trim() === "" ? null : Number(confidence);
  const confidenceInvalid =
    confidenceValue !== null &&
    (Number.isNaN(confidenceValue) || confidenceValue < 0 || confidenceValue > 1);

  const canSubmit =
    content.trim() !== "" &&
    source.trim() !== "" &&
    project.trim() !== "" &&
    !confidenceInvalid &&
    !busy;

  return (
    <form
      className="form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit) return;
        onSubmit({
          content: content.trim(),
          category,
          source: source.trim(),
          project: project.trim(),
          confidence: confidenceValue,
        });
      }}
    >
      <h2 className="form-heading">{initial ? "Edit memory" : "Add a memory"}</h2>

      <label htmlFor="content">Content</label>
      <textarea
        id="content"
        value={content}
        rows={4}
        required
        maxLength={4000}
        placeholder="We disabled Redis caching for user records because stale entries caused wrong balances."
        onChange={(event) => setContent(event.target.value)}
      />

      <div className="form-row">
        <div>
          <label htmlFor="category">Category</label>
          <select
            id="category"
            value={category}
            onChange={(event) => setCategory(event.target.value as MemoryCategory)}
          >
            {CATEGORIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="project">Project</label>
          <input
            id="project"
            value={project}
            required
            maxLength={100}
            placeholder="payments-api"
            onChange={(event) => setProject(event.target.value)}
          />
        </div>
      </div>

      <div className="form-row">
        <div>
          <label htmlFor="source">Source</label>
          <input
            id="source"
            value={source}
            required
            maxLength={200}
            placeholder="incident-142"
            onChange={(event) => setSource(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="confidence">Confidence (0–1, optional)</label>
          <input
            id="confidence"
            value={confidence}
            inputMode="decimal"
            placeholder="0.9"
            aria-invalid={confidenceInvalid}
            aria-describedby={confidenceInvalid ? "confidence-error" : undefined}
            onChange={(event) => setConfidence(event.target.value)}
          />
          {confidenceInvalid && (
            <p className="field-error" id="confidence-error">
              Use a number between 0 and 1, or leave empty.
            </p>
          )}
        </div>
      </div>

      <div className="form-actions">
        <button type="submit" className="button button-primary" disabled={!canSubmit}>
          {busy ? "Saving…" : initial ? "Save changes" : "Add memory"}
        </button>
        {onCancel && (
          <button type="button" className="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
