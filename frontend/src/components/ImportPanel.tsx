import { useRef, useState } from "react";
import type { MemoryCreateInput } from "../types";

interface Props {
  busy: boolean;
  onImport: (entries: MemoryCreateInput[]) => void;
}

/** Accepts either a bare array (like data/sample_memories.json) or { memories: [...] }. */
export function parseImportPayload(text: string): MemoryCreateInput[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    // Surfacing the parser's own message is far more useful than "invalid JSON":
    // it includes the position of the offending character.
    throw new Error(
      `Invalid JSON: ${error instanceof Error ? error.message : "could not parse"}`,
    );
  }

  const entries = Array.isArray(parsed)
    ? parsed
    : typeof parsed === "object" &&
        parsed !== null &&
        Array.isArray((parsed as { memories?: unknown }).memories)
      ? ((parsed as { memories: unknown[] }).memories)
      : null;

  if (entries === null) {
    throw new Error(
      'Expected a JSON array of memories, or an object like {"memories": [...]}.',
    );
  }

  if (entries.length === 0) {
    throw new Error("The array is empty; there is nothing to import.");
  }

  return entries as MemoryCreateInput[];
}

export function ImportPanel({ busy, onImport }: Props) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      onImport(parseImportPayload(text));
    } catch (parseError) {
      setError(parseError instanceof Error ? parseError.message : "Invalid input");
    }
  };

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    const contents = await file.text();
    setText(contents);
  };

  return (
    <form className="form" onSubmit={handleSubmit}>
      <h2 className="form-heading">Import memories</h2>
      <p className="hint">
        Paste a JSON array, or load a file. A single invalid entry rejects the whole
        batch — nothing is written.
      </p>

      <label htmlFor="import-json">JSON</label>
      <textarea
        id="import-json"
        rows={6}
        className="mono"
        value={text}
        placeholder='[{"content": "...", "category": "decision", "source": "...", "project": "..."}]'
        onChange={(event) => setText(event.target.value)}
      />

      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}

      <div className="form-actions">
        <button
          type="submit"
          className="button button-primary"
          disabled={busy || text.trim() === ""}
        >
          {busy ? "Importing…" : "Import"}
        </button>
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => fileInput.current?.click()}
        >
          Load file…
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          hidden
          aria-label="Load memories from a JSON file"
          onChange={(event) => void handleFile(event.target.files?.[0])}
        />
      </div>
    </form>
  );
}
