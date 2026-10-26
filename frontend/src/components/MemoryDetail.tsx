import { useState } from "react";
import type { Memory } from "../types";

interface Props {
  memory: Memory;
  onEdit: () => void;
  onDelete: () => void;
  busy: boolean;
}

export function MemoryDetail({ memory, onEdit, onDelete, busy }: Props) {
  // Deletion is irreversible, so it takes a second, deliberate click. An inline
  // confirmation is used instead of window.confirm so it can be styled, tested
  // and reused in later phases.
  const [confirming, setConfirming] = useState(false);

  const rows: Array<[string, string]> = [
    ["Category", memory.category],
    ["Project", memory.project],
    ["Source", memory.source],
    ["Confidence", memory.confidence === null ? "not set" : String(memory.confidence)],
    ["Status", memory.status],
    ["Superseded by", memory.superseded_by ?? "—"],
    ["Created", new Date(memory.created_at).toLocaleString()],
    ["Updated", new Date(memory.updated_at).toLocaleString()],
    ["ID", memory.id],
  ];

  return (
    <article className="detail" aria-label="Memory detail">
      <h2 className="detail-heading">Memory detail</h2>
      <p className="detail-content">{memory.content}</p>

      <dl className="detail-grid">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className={label === "ID" ? "mono" : undefined}>{value}</dd>
          </div>
        ))}
      </dl>

      {confirming ? (
        <div className="detail-actions" role="group" aria-label="Confirm deletion">
          <p className="hint">This cannot be undone.</p>
          <button
            type="button"
            className="button button-danger"
            onClick={onDelete}
            disabled={busy}
          >
            Yes, delete permanently
          </button>
          <button
            type="button"
            className="button"
            onClick={() => setConfirming(false)}
            disabled={busy}
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="detail-actions">
          <button type="button" className="button" onClick={onEdit} disabled={busy}>
            Edit
          </button>
          <button
            type="button"
            className="button button-danger"
            onClick={() => setConfirming(true)}
            disabled={busy}
          >
            Delete
          </button>
        </div>
      )}
    </article>
  );
}
