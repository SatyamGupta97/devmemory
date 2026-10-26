/** Shared types mirroring the backend's Pydantic schemas.
 *
 * These are hand-maintained, not generated. If a field is renamed in
 * backend/app/schemas.py it must change here too — the compiler will find every
 * place that breaks, which is the point of typing the API boundary.
 */

export const CATEGORIES = [
  "decision",
  "constraint",
  "failure",
  "convention",
  "fact",
] as const;

export type MemoryCategory = (typeof CATEGORIES)[number];

export type MemoryStatus = "active" | "superseded";

export interface Memory {
  id: string;
  content: string;
  category: MemoryCategory;
  source: string;
  project: string;
  created_at: string;
  updated_at: string;
  confidence: number | null;
  status: MemoryStatus;
  superseded_by: string | null;
}

/** Fields a client may send when creating a memory. */
export interface MemoryCreateInput {
  content: string;
  category: MemoryCategory;
  source: string;
  project: string;
  confidence?: number | null;
}

/** Fields a client may change. Omitted fields are left untouched. */
export type MemoryUpdateInput = Partial<{
  content: string;
  category: MemoryCategory;
  source: string;
  project: string;
  confidence: number | null;
  status: MemoryStatus;
  superseded_by: string | null;
}>;

export interface ImportResult {
  imported: number;
  ids: string[];
}
