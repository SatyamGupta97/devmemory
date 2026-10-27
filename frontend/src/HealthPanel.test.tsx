import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { HealthReport, Memory } from "./types";

function memory(overrides: Partial<Memory> = {}): Memory {
  return {
    id: "mem-1",
    content: "The user service uses PostgreSQL 15 for persistence.",
    category: "decision",
    source: "architecture-review",
    project: "payments-api",
    created_at: "2026-03-01T10:00:00Z",
    updated_at: "2026-03-01T10:00:00Z",
    confidence: 0.9,
    status: "active",
    superseded_by: null,
    ...overrides,
  };
}

function report(overrides: Partial<HealthReport> = {}): HealthReport {
  return {
    generated_at: "2026-10-26T12:00:00Z",
    analyzer: "deterministic-rules",
    total_memories: 2,
    projects: ["payments-api"],
    summary: { exact_duplicate: 1, potential_contradiction: 1 },
    findings: [
      {
        id: "exact_duplicate:mem-1",
        issue_type: "exact_duplicate",
        severity: "medium",
        title: "Exact duplicate memory",
        explanation: "These two memories are identical.",
        evidence: ["[mem-1] payments-api", "[mem-2] payments-api"],
        memory_ids: ["mem-1", "mem-2"],
        suggested_action: "Keep one and delete the other.",
        uncertainty: null,
      },
      {
        id: "potential_contradiction:mem-3",
        issue_type: "potential_contradiction",
        severity: "high",
        title: "Potential contradiction between memories",
        explanation: "These memories name different values.",
        evidence: ["[mem-1] postgres", "[mem-3] mysql"],
        memory_ids: ["mem-1", "mem-3"],
        suggested_action: "Confirm the current state.",
        uncertainty: "This is a candidate, not a verdict.",
      },
    ],
    limitations: ["Staleness is inferred from age alone."],
    ...overrides,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const DEFAULT_STATUS = {
  provider: "local",
  model: "hashed-ngrams-1024",
  dimensions: 1024,
  captures_meaning: false,
  description: "Surface form only.",
  total_memories: 1,
  indexed_memories: 1,
  stale_memories: 0,
};

function mockApi(handlers: Record<string, () => Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const key = `${method} ${new URL(String(input)).pathname}`;
    const handler = handlers[key];
    if (!handler) {
      if (key === "GET /api/embeddings/status") {
        return json(DEFAULT_STATUS);
      }
      throw new Error(`Unhandled request in test: ${key}`);
    }
    return handler();
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("health check", () => {
  it("shows no report until the check is run", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);

    expect(
      screen.queryByRole("region", { name: "Memory health check" }),
    ).not.toBeInTheDocument();
  });

  it("shows the findings and the analyzer that produced them", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(report()),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);

    await user.click(screen.getByRole("button", { name: "Run health check" }));

    const panel = await screen.findByRole("region", { name: "Memory health check" });
    // Scoped to the findings list: the summary chips repeat the same labels.
    const findings = within(panel).getByRole("list", { name: "Findings" });
    expect(within(findings).getByText("Exact duplicate")).toBeInTheDocument();
    expect(within(findings).getByText("Potential contradiction")).toBeInTheDocument();
    // The user must know no model was involved.
    expect(within(panel).getByText(/no language model was used/)).toBeInTheDocument();
  });

  it("shows the evidence and the suggested action for a finding", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(report()),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);
    await user.click(screen.getByRole("button", { name: "Run health check" }));

    const panel = await screen.findByRole("region", { name: "Memory health check" });
    const findings = within(panel).getByRole("list", { name: "Findings" });
    // Both findings show two evidence lines, so target the first one.
    await user.click(within(findings).getAllByText("Evidence (2)")[0]!);

    expect(within(findings).getByText("[mem-1] postgres")).toBeInTheDocument();
    expect(
      within(findings).getByText(/Keep one and delete the other/),
    ).toBeInTheDocument();
  });

  it("shows uncertainty when the finding is not certain", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(report()),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);
    await user.click(screen.getByRole("button", { name: "Run health check" }));

    const panel = await screen.findByRole("region", { name: "Memory health check" });
    const findings = within(panel).getByRole("list", { name: "Findings" });
    expect(within(findings).getByText(/candidate, not a verdict/)).toBeInTheDocument();
  });

  it("lists the limitations of the analysis", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(report()),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);
    await user.click(screen.getByRole("button", { name: "Run health check" }));

    const panel = await screen.findByRole("region", { name: "Memory health check" });
    await user.click(within(panel).getByText("What this check cannot tell you"));

    expect(
      within(panel).getByText("Staleness is inferred from age alone."),
    ).toBeInTheDocument();
  });

  it("selects a memory when its id is clicked", async () => {
    mockApi({
      "GET /api/memories": () =>
        json([memory(), memory({ id: "mem-2", content: "Never log full card numbers." })]),
      "GET /api/health": () => json(report()),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);
    await user.click(screen.getByRole("button", { name: "Run health check" }));

    const panel = await screen.findByRole("region", { name: "Memory health check" });
    const findings = within(panel).getByRole("list", { name: "Findings" });
    await user.click(within(findings).getByRole("button", { name: "mem-2" }));

    const detail = screen.getByRole("article", { name: "Memory detail" });
    expect(within(detail).getByText("mem-2")).toBeInTheDocument();
  });

  it("reports a clean collection without inventing problems", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () =>
        json(
          report({
            findings: [],
            summary: {},
            total_memories: 1,
          }),
        ),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);
    await user.click(screen.getByRole("button", { name: "Run health check" }));

    const panel = await screen.findByRole("region", { name: "Memory health check" });
    expect(within(panel).getByText(/No problems found/)).toBeInTheDocument();
  });

  it("shows an error when the health check cannot run", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json({ detail: "analysis failed" }, 500),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);
    await user.click(screen.getByRole("button", { name: "Run health check" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("analysis failed");
  });

  it("scopes the health check to the active project filter", async () => {
    const fetchMock = mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(report()),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Filter by project" }),
      "payments-api",
    );
    await user.click(screen.getByRole("button", { name: "Run health check" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/health?project=payments-api"),
        expect.anything(),
      ),
    );
  });
});
