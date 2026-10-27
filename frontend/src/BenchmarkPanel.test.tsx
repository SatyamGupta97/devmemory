import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { BenchmarkReport, Memory } from "./types";

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

function report(overrides: Partial<BenchmarkReport> = {}): BenchmarkReport {
  return {
    generated_at: "2026-10-26T12:00:00Z",
    strategy: "keyword-bm25",
    summary: {
      strategy: "keyword-bm25",
      k: 5,
      query_count: 2,
      valid_queries: 2,
      invalid_queries: 0,
      mean_precision_at_k: 0.727,
      mean_recall_at_k: 0.833,
      mrr: 0.8,
      total_missed: 1,
      total_irrelevant_retrieved: 3,
      unresolved_expectations: 0,
    },
    cases: [
      {
        query_id: "q01",
        kind: "direct",
        project: "payments-api",
        query: "Which database?",
        k: 5,
        valid: true,
        expected_count: 1,
        returned_count: 1,
        relevant_retrieved: ["mem-1"],
        missed: [],
        irrelevant_retrieved: [],
        unresolved_expectations: [],
        precision_at_k: 1.0,
        recall_at_k: 1.0,
        reciprocal_rank: 1.0,
        first_relevant_rank: 1,
      },
      {
        query_id: "q02",
        kind: "paraphrase",
        project: "payments-api",
        query: "How do we handle duplicate events?",
        k: 5,
        valid: true,
        expected_count: 1,
        returned_count: 4,
        relevant_retrieved: [],
        missed: ["Stripe webhook handlers must be idempotent."],
        irrelevant_retrieved: ["mem-1"],
        unresolved_expectations: [],
        precision_at_k: 0.0,
        recall_at_k: 0.0,
        reciprocal_rank: 0.0,
        first_relevant_rank: null,
      },
    ],
    notes: ["Metrics come from the actual ranked output of the strategy under test."],
    ...overrides,
  };
}

function semanticReport(): BenchmarkReport {
  return report({
    strategy: "semantic-embedding",
    summary: {
      ...report().summary,
      strategy: "semantic-embedding",
      mean_precision_at_k: 0.66,
      mean_recall_at_k: 0.944,
      mrr: 0.917,
      total_missed: 0,
    },
    cases: report().cases.map((case_) => ({
      ...case_,
      recall_at_k: 1.0,
      reciprocal_rank: 1.0,
      missed: [],
    })),
  });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const DEFINITION = {
  version: 1,
  description: "test",
  default_k: 5,
  queries: [
    {
      id: "q01",
      kind: "direct",
      project: "payments-api",
      query: "Which database?",
      expected: [],
      why: null,
      k: null,
    },
    {
      id: "q02",
      kind: "paraphrase",
      project: "payments-api",
      query: "How do we handle duplicate events?",
      expected: [],
      why: null,
      k: null,
    },
  ],
};

const STATUS = {
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
    const key = `${init?.method ?? "GET"} ${new URL(String(input)).pathname}`;
    const handler = handlers[key];
    if (handler) return handler();
    if (key === "GET /api/embeddings/status") return json(STATUS);
    if (key === "GET /api/benchmark") return json(DEFINITION);
    throw new Error(`Unhandled request in test: ${key}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function openBenchmark() {
  render(<App />);
  await screen.findByText(/disabled Redis caching/);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Benchmark" }));
  return { user, panel: screen.getByRole("region", { name: "Retrieval benchmark" }) };
}

describe("retrieval benchmark", () => {
  it("is hidden until requested", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });

    render(<App />);
    await screen.findByText(/disabled Redis caching/);

    expect(
      screen.queryByRole("region", { name: "Retrieval benchmark" }),
    ).not.toBeInTheDocument();
  });

  it("describes the benchmark before running it", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });

    const { panel } = await openBenchmark();

    expect(await within(panel).findByText(/2 version-controlled queries/)).toBeInTheDocument();
    expect(
      within(panel).getByText(/survives re-importing/),
    ).toBeInTheDocument();
  });

  it("shows measured metrics for keyword", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/benchmark/run": () => json(report()),
    });

    const { user, panel } = await openBenchmark();
    await user.click(within(panel).getByRole("button", { name: "Run keyword" }));

    expect(await within(panel).findByText("0.727")).toBeInTheDocument();
    expect(within(panel).getByText("0.833")).toBeInTheDocument();
    expect(within(panel).getByText("0.800")).toBeInTheDocument();
  });

  it("tabulates each query with its own outcome", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/benchmark/run": () => json(report()),
    });

    const { user, panel } = await openBenchmark();
    await user.click(within(panel).getByRole("button", { name: "Run keyword" }));

    const table = await within(panel).findByRole("table");
    expect(within(table).getByText("q01")).toBeInTheDocument();
    expect(within(table).getByText("q02")).toBeInTheDocument();
    expect(within(table).getByText("paraphrase")).toBeInTheDocument();
    // The missed memory is named, not just counted.
    expect(
      within(table).getByText("Stripe webhook handlers must be idempotent."),
    ).toBeInTheDocument();
  });

  it("compares both strategies side by side", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/benchmark/run": () => json(report()),
    });
    // Route by body so both strategies get their own report.
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${new URL(String(input)).pathname}`;
      if (key === "POST /api/benchmark/run") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        return json(body.strategy === "semantic" ? semanticReport() : report());
      }
      if (key === "GET /api/memories") return json([memory()]);
      if (key === "GET /api/embeddings/status") return json(STATUS);
      if (key === "GET /api/benchmark") return json(DEFINITION);
      throw new Error(`Unhandled: ${key}`);
    });

    const { user, panel } = await openBenchmark();
    await user.click(
      within(panel).getByRole("button", { name: "Compare keyword vs semantic" }),
    );

    expect(await within(panel).findByText("Keyword (BM25)")).toBeInTheDocument();
    expect(within(panel).getByText("Semantic (vectors)")).toBeInTheDocument();
    // Both figures appear, so the comparison is real rather than a single number.
    await waitFor(() => {
      expect(within(panel).getByText("0.944")).toBeInTheDocument();
    });
  });

  it("keeps the keyword result when the semantic run fails", async () => {
    const fetchMock = mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/benchmark/run": () => json(report()),
    });
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${new URL(String(input)).pathname}`;
      if (key === "POST /api/benchmark/run") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        return body.strategy === "semantic"
          ? json({ detail: "No embeddings are indexed." }, 409)
          : json(report());
      }
      if (key === "GET /api/memories") return json([memory()]);
      if (key === "GET /api/embeddings/status") return json(STATUS);
      if (key === "GET /api/benchmark") return json(DEFINITION);
      throw new Error(`Unhandled: ${key}`);
    });

    const { user, panel } = await openBenchmark();
    await user.click(
      within(panel).getByRole("button", { name: "Compare keyword vs semantic" }),
    );

    expect(
      await within(panel).findByText(/Semantic strategy unavailable/),
    ).toBeInTheDocument();
    // The keyword numbers are still on screen.
    expect(within(panel).getByText("0.727")).toBeInTheDocument();
  });

  it("states what the numbers do not prove", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/benchmark/run": () => json(report()),
    });

    const { user, panel } = await openBenchmark();
    await user.click(within(panel).getByRole("button", { name: "Run keyword" }));
    await user.click(
      await within(panel).findByText("What these numbers do and do not prove"),
    );

    expect(
      within(panel).getByText(/actual ranked output of the strategy under test/),
    ).toBeInTheDocument();
  });

  it("marks a query whose ground truth does not resolve", async () => {
    const broken = report();
    broken.cases[1] = {
      ...broken.cases[1]!,
      valid: false,
      unresolved_expectations: ["A memory that is not imported."],
    };
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/benchmark/run": () => json(broken),
    });

    const { user, panel } = await openBenchmark();
    await user.click(within(panel).getByRole("button", { name: "Run keyword" }));

    const table = await within(panel).findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows.some((row) => row.className.includes("row-invalid"))).toBe(true);
  });

  it("closes when asked", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });

    const { user, panel } = await openBenchmark();
    await user.click(within(panel).getByRole("button", { name: "Close" }));

    expect(
      screen.queryByRole("region", { name: "Retrieval benchmark" }),
    ).not.toBeInTheDocument();
  });
});