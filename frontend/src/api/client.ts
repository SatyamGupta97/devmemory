/** Typed HTTP client for the DevMemory API.
 *
 * Every call goes through `request`, so error handling and status checking
 * exist in exactly one place. Components never touch `fetch`.
 */

import type {
  HealthReport,
  ImportResult,
  Memory,
  MemoryCategory,
  MemoryCreateInput,
  MemoryUpdateInput,
} from "../types";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

/** An error the API answered with, carrying the status and a readable message. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** A FastAPI 422 body: one entry per invalid field. */
interface ValidationIssue {
  loc: Array<string | number>;
  msg: string;
}

function messageFromBody(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null) {
    const detail = (body as { detail?: unknown }).detail;

    // 404/409/422-from-rules: detail is a plain string from HTTPException.
    if (typeof detail === "string") {
      return detail;
    }

    // 422 from request validation: detail is a list of field issues. Showing the
    // field name matters, otherwise "invalid input" is unactionable.
    if (Array.isArray(detail)) {
      const issues = detail.filter(
        (item): item is ValidationIssue =>
          typeof item === "object" &&
          item !== null &&
          Array.isArray((item as ValidationIssue).loc),
      );
      if (issues.length > 0) {
        return issues
          .map((issue) => {
            const path = issue.loc
              .filter((part) => part !== "body")
              .map(String)
              .join(".");
            return path ? `${path}: ${issue.msg}` : issue.msg;
          })
          .join("; ");
      }
    }
  }

  return `Request failed with status ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    // fetch only rejects when no HTTP response was produced at all: server down,
    // wrong URL, CORS block, DNS failure. That is a different problem from a 4xx
    // and needs a different message for the user.
    throw new ApiError(
      0,
      `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`,
    );
  }

  // fetch does NOT reject on 4xx/5xx, so this check is required.
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, messageFromBody(body, response.status));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function listMemories(
  filters: { project?: string; category?: MemoryCategory } = {},
): Promise<Memory[]> {
  const params = new URLSearchParams();
  if (filters.project) params.set("project", filters.project);
  if (filters.category) params.set("category", filters.category);
  const query = params.toString();

  return request<Memory[]>(`/api/memories${query ? `?${query}` : ""}`);
}

export async function createMemory(input: MemoryCreateInput): Promise<Memory> {
  return request<Memory>("/api/memories", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateMemory(
  id: string,
  input: MemoryUpdateInput,
): Promise<Memory> {
  return request<Memory>(`/api/memories/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteMemory(id: string): Promise<void> {
  await request<void>(`/api/memories/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function importMemories(
  memories: MemoryCreateInput[],
): Promise<ImportResult> {
  return request<ImportResult>("/api/memories/import", {
    method: "POST",
    body: JSON.stringify({ memories }),
  });
}

export async function getHealthReport(
  project?: string,
): Promise<HealthReport> {
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  return request<HealthReport>(`/api/health${query}`);
}
