import type { Memory } from "../types";

interface Props {
  memories: Memory[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString();
}

export function MemoryList({ memories, selectedId, onSelect }: Props) {
  return (
    <ul className="memory-list" aria-label="Memories">
      {memories.map((memory) => (
        <li key={memory.id}>
          <button
            type="button"
            className={`memory-card${memory.id === selectedId ? " is-selected" : ""}`}
            onClick={() => onSelect(memory.id)}
            aria-current={memory.id === selectedId}
          >
            <div className="memory-card-top">
              <span className={`badge badge-${memory.category}`}>{memory.category}</span>
              <span className="memory-card-project">{memory.project}</span>
              {memory.status === "superseded" && (
                <span className="badge badge-superseded">superseded</span>
              )}
            </div>
            <p className="memory-card-content">{memory.content}</p>
            <div className="memory-card-meta">
              <span>{memory.source}</span>
              <span>·</span>
              <span>{formatDate(memory.created_at)}</span>
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}
