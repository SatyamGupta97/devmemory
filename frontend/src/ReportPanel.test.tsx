import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { InspectorReport, Memory } from "./types";

function memory(): Memory {
  return {
    id: "mem-1",
    content: "We disabled Redis caching for user records.",
    category: "failure",
    source: "incident-142",
    project: "payments-api",
    created_at: "2025-11-02T09:00:00Z",
    updated_at: "2025-11-02T09:00:00Z",
    confidence: 0.95,
    status: "active",
    superseded_by: null,
  };
}

function benchmarkSummary(overrides: Record<string, unknown> = {}) {
  return {
    strategy: "keyword-bm25",
    k: 5,
    query_count: 10,
    valid_queries: 10,
    invalid_queries: 0,
    mean_precision_at_k: 0.727,
    mean_recall_at_k: 0.833,
    mrr: 0.806,
    total_missed: 2,
    total_irrelevant_retrieved: 7,
    unresolved_expectations: 0,
    ...overrides,
  };
}

function report(overrides: Partial<InspectorReport> = {}): InspectorReport {
  return {
    generated_at: "2026-10-26T12:00:00Z",
    scope_project: null,
    inventory: {
      total: 19,
      by_project: { analytics: 7, "payments-api": 11 },
      by_category: { decision: 7 },
      by_status: { active: 19 },
      with_confidence: 14,
      without_confidence: 5,
    },
    health: {
      generated_at: "2026-10-26T12:00:00Z",
      analyzer: "deterministic-rules",
      total_memories: 19,
      projects: ["analytics"],
      summary: { potential_contradiction: 3, potentially_stale: 7 },
      findings: [],
      limitations: ["Staleness is inferred from age alone."],
    },
    ai: {
      consulted: false,
      model: null,
      reason: "AI-assisted analysis is not configured.",
      findings: [],
      rejected: [],
    },
    retrieval: {
      keyword: {
        generated_at: "2026-10-26T12:00:00Z",
        strategy: "keyword-bm25",
        summary: benchmarkSummary(),
        cases: [],
        notes: [],
      },
      semantic: {
        generated_at: "2026-10-26T12:00:00Z",
        strategy: "semantic-embedding",
        summary: benchmarkSummary({
          strategy: "semantic-embedding",
          mean_precision_at_k: 0.66,
          mean_recall_at_k: 0.944,
          mrr: 0.917,
          total_missed: 1,
        }),
        cases: [],
        notes: [],
      },
      missed_examples: [
        {
          query_id: "q05-duplicate-events",
          query: "How do we handle duplicate refund events?",
          missed: ["Stripe webhook handlers must be idempotent."],
          expected_count: 1,
        },
      ],
    },
    recommendations: [
      {
        priority: "high",
        title: "Resolve 3 potential contradiction(s)",
        rationale: "Three findings pair memories that name different values.",
        related: ["a", "b", "c"],
      },
      {
        priority: "low",
        title: "Configure a language model for meaning-based findings",
        rationale: "AI analysis is not configured.",
        related: [],
      },
    ],
    context: {
      retrieval_strategy: "keyword-bm25+semantic-embedding",
      benchmark_version: 1,
      benchmark_query_count: 10,
      benchmark_k: 5,
      embedding_provider: "local",
      embedding_model: "hashed-ngrams-1024",
      embedding_captures_meaning: false,
      embeddings_indexed: 19,
      embeddings_stale: 0,
      ai_consulted: false,
      ai_model: null,
      ai_unavailable_reason: "not configured",
    },
    notes: ["Every count was computed from the stored data."],
    ...overrides,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockApi(handlers: Record<string, () => Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${new URL(String(input)).pathname}`;
    const handler = handlers[key];
    if (handler) return handler();
    if (key === "GET /api/health/ai/status") {
      return json({ available: false, provider: "none", model: "", reason: "no key" });
    }
    if (key === "GET /api/embeddings/status") {
      return json({
        provider: "local",
        model: "hashed-ngrams-1024",
        dimensions: 1024,
        captures_meaning: false,
        description: "Surface form only.",
        total_memories: 1,
        indexed_memories: 1,
        stale_memories: 0,
      });
    }
    throw new Error(`Unhandled request in test: ${key}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function openReport() {
  render(<App />);
  await screen.findByText(/disabled Redis caching/);
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "Report" }));
  return {
    user,
    panel: await screen.findByRole("region", { name: "Inspector report" }),
  };
}

describe("inspector report", () => {
  it("is hidden until requested and loads when opened", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });

    render(<App />);
    await screen.findByText(/disabled Redis caching/);
    expect(
      screen.queryByRole("region", { name: "Inspector report" }),
    ).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Report" }));

    expect(
      await screen.findByRole("region", { name: "Inspector report" }),
    ).toBeInTheDocument();
  });

  it("shows the measurement context before the numbers", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });

    const { panel } = await openReport();

    const context = within(panel).getByText("How this was measured").closest("div");
    expect(within(context!).getByText(/10 queries/)).toBeInTheDocument();
    expect(within(context!).getByText("hashed-ngrams-1024")).toBeInTheDocument();
    expect(within(panel).getByText(/surface form only/)).toBeInTheDocument();
  });

  it("warns that a surface provider is not a semantic model", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });

    const { panel } = await openReport();

    expect(
      within(panel).getByText(/not a semantic model/),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/lower bound/)).toBeInTheDocument();
  });

  it("shows inventory and deterministic finding counts", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });

    const { panel } = await openReport();

    expect(within(panel).getByText(/19 memories in 2 projects/)).toBeInTheDocument();
    expect(within(panel).getByText("14 of 19 have a confidence value.")).toBeInTheDocument();
    expect(within(panel).getByText("potential contradiction")).toBeInTheDocument();
  });

  it("compares keyword and semantic metrics side by side", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });

    const { panel } = await openReport();

    expect(within(panel).getByText("0.727")).toBeInTheDocument();
    expect(within(panel).getByText("0.660")).toBeInTheDocument();
    expect(within(panel).getByText("0.944")).toBeInTheDocument();
  });

  it("lists retrieval failures with the missed memory", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });

    const { user, panel } = await openReport();
    await user.click(within(panel).getByText(/Retrieval failures \(1\)/));

    expect(
      within(panel).getByText("Stripe webhook handlers must be idempotent."),
    ).toBeInTheDocument();
  });

  it("shows recommendations with their priority", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });

    const { panel } = await openReport();

    expect(
      within(panel).getByText("Resolve 3 potential contradiction(s)"),
    ).toBeInTheDocument();
    expect(within(panel).getByText("high")).toBeInTheDocument();
    expect(
      within(panel).getByText("Configure a language model for meaning-based findings"),
    ).toBeInTheDocument();
  });

  it("offers export links that carry the scope", async () => {
    const fetchMock = mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/disabled Redis caching/);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Filter by project" }),
      "payments-api",
    );
    await user.click(screen.getByRole("tab", { name: "Report" }));

    const panel = await screen.findByRole("region", { name: "Inspector report" });
    const markdown = within(panel).getByRole("link", { name: "Export Markdown" });
    expect(markdown).toHaveAttribute(
      "href",
      expect.stringContaining("format=markdown"),
    );
    expect(markdown.getAttribute("href")).toContain("project=payments-api");
    expect(
      within(panel).getByRole("link", { name: "Export JSON" }).getAttribute("href"),
    ).toContain("format=json");
    expect(fetchMock).toHaveBeenCalled();
  });

  it("labels model-generated findings and keeps them separate", async () => {
    const withAi = report();
    withAi.ai = {
      consulted: true,
      model: "test-model",
      reason: null,
      findings: [
        {
          id: "ai-0",
          issue_type: "semantic_duplicate",
          severity: "medium",
          title: "Same lesson twice",
          explanation: "Both describe a cache disabled after stale data.",
          evidence: ["a"],
          memory_ids: ["mem-1"],
          suggested_action: "Merge.",
          uncertainty: "low",
          source: "model",
        },
      ],
      rejected: [],
    };
    withAi.context = { ...withAi.context, ai_consulted: true, ai_model: "test-model" };
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(withAi),
    });

    const { panel } = await openReport();

    expect(within(panel).getByText("Model-generated findings")).toBeInTheDocument();
    expect(within(panel).getByText("Model-generated.")).toBeInTheDocument();
    expect(within(panel).getByText(/Same lesson twice/)).toBeInTheDocument();
  });

  it("says plainly when no model was consulted", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });

    const { panel } = await openReport();

    expect(within(panel).getByText("not consulted")).toBeInTheDocument();
    expect(
      within(panel).queryByText("Model-generated findings"),
    ).not.toBeInTheDocument();
  });

  it("states the report's limitations", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => json(report()),
    });

    const { user, panel } = await openReport();
    await user.click(within(panel).getByText("What this report does not tell you"));

    expect(
      within(panel).getByText(/Every count was computed from the stored data/),
    ).toBeInTheDocument();
  });

  it("shows an error with a retry when the report cannot be built", async () => {
    let attempt = 0;
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/report": () => {
        attempt += 1;
        return attempt === 1
          ? json({ detail: "Benchmark file not found." }, 404)
          : json(report());
      },
    });

    const { user, panel } = await openReport();

    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      "Benchmark file not found.",
    );
    await user.click(within(panel).getByRole("button", { name: "Retry" }));
    expect(await within(panel).findByText(/19 memories/)).toBeInTheDocument();
  });
});