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

/** Health check types, mirroring the backend's health schemas. */

export type IssueType =
  | "exact_duplicate"
  | "near_duplicate"
  | "potential_contradiction"
  | "potentially_stale"
  | "superseded_memory"
  | "missing_confidence"
  | "low_confidence"
  | "unreliable_source"
  | "placeholder_project"
  | "vague_content"
  | "suspicious_content";

export type Severity = "high" | "medium" | "low" | "info";

export interface HealthFinding {
  id: string;
  issue_type: IssueType;
  severity: Severity;
  title: string;
  explanation: string;
  evidence: string[];
  memory_ids: string[];
  suggested_action: string;
  uncertainty: string | null;
}

export interface HealthReport {
  generated_at: string;
  analyzer: string;
  total_memories: number;
  projects: string[];
  summary: Record<string, number>;
  findings: HealthFinding[];
  limitations: string[];
}

/** Retrieval types, mirroring the backend's retrieval schemas. */

export interface MatchedTerm {
  term: string;
  idf: number;
  term_frequency: number;
  contribution: number;
}

export interface RetrievalMatch {
  memory: Memory;
  /** Which strategy produced this match. */
  method: string;
  score: number;
  matched_terms: MatchedTerm[];
  explanation: string;
}

export interface RetrievalResult {
  query: string;
  strategy: string;
  project: string | null;
  considered: number;
  returned: number;
  matches: RetrievalMatch[];
  unmatched_query_terms: string[];
  notes: string[];
}

/** Embedding index types. */

export type RetrievalStrategy = "keyword" | "semantic";

export interface EmbeddingStatus {
  provider: string;
  model: string;
  dimensions: number;
  captures_meaning: boolean;
  description: string;
  total_memories: number;
  indexed_memories: number;
  stale_memories: number;
}

export interface IndexResult {
  provider: string;
  model: string;
  dimensions: number;
  captures_meaning: boolean;
  total: number;
  indexed: number;
  skipped: number;
  failed: number;
  errors: string[];
}

/** Benchmark types. */

export interface BenchmarkExpectation {
  content: string;
  why: string | null;
}

export interface BenchmarkQueryDefinition {
  id: string;
  kind: string;
  project: string | null;
  query: string;
  expected: BenchmarkExpectation[];
  why: string | null;
  k: number | null;
}

export interface BenchmarkDefinition {
  version: number;
  description: string;
  default_k: number;
  queries: BenchmarkQueryDefinition[];
}

export interface BenchmarkCaseResult {
  query_id: string;
  kind: string;
  project: string | null;
  query: string;
  k: number;
  valid: boolean;
  expected_count: number;
  returned_count: number;
  relevant_retrieved: string[];
  missed: string[];
  irrelevant_retrieved: string[];
  unresolved_expectations: string[];
  precision_at_k: number;
  recall_at_k: number | null;
  reciprocal_rank: number | null;
  first_relevant_rank: number | null;
}

export interface BenchmarkSummary {
  strategy: string;
  k: number;
  query_count: number;
  valid_queries: number;
  invalid_queries: number;
  mean_precision_at_k: number;
  mean_recall_at_k: number | null;
  mrr: number | null;
  total_missed: number;
  total_irrelevant_retrieved: number;
  unresolved_expectations: number;
}

export interface BenchmarkReport {
  generated_at: string;
  strategy: string;
  summary: BenchmarkSummary;
  cases: BenchmarkCaseResult[];
  notes: string[];
}
