import type { Memory } from "../types";

interface Props {
  memories: Memory[];
}

/** Counts derived from the loaded memories, never hardcoded. */
export function StatsBar({ memories }: Props) {
  const projects = new Set(memories.map((memory) => memory.project));
  const superseded = memories.filter(
    (memory) => memory.status === "superseded",
  ).length;

  const stats = [
    { label: "Memories", value: memories.length },
    { label: "Projects", value: projects.size },
    { label: "Active", value: memories.length - superseded },
    { label: "Superseded", value: superseded },
  ];

  return (
    <ul className="stats" aria-label="Memory totals">
      {stats.map((stat) => (
        <li className="stat" key={stat.label}>
          <span className="stat-value">{stat.value}</span>
          <span className="stat-label">{stat.label}</span>
        </li>
      ))}
    </ul>
  );
}
