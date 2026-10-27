import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { AiAnalysisReport, HealthReport, Memory } from "./types";

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

function healthReport(): HealthReport {
  return {
    generated_at: "2026-10-26T12:00:00Z",
    analyzer: "deterministic-rules",
    total_memories: 1,
    projects: ["payments-api"],
    summary: {},
    findings: [],
    limitations: [],
  };
}

function aiReport(overrides: Partial<AiAnalysisReport> = {}): AiAnalysisReport {
  return {
    generated_at: "2026-10-26T12:00:00Z",
    provider: "hosted",
    model: "test-model",
    analyzed_memories: 1,
    excluded_memories: [],
    findings: [
      {
        id: "ai-0-semantic_duplicate-mem-1",
        issue_type: "semantic_duplicate",
        severity: "medium",
        title: "Two memories record the same lesson",
        explanation: "Both describe disabling a cache after stale data.",
        evidence: ["We disabled Redis caching", "We removed the in-memory snapshot"],
        memory_ids: ["mem-1"],
        suggested_action: "Merge them into one memory.",
        uncertainty: "low",
        source: "model",
      },
    ],
    rejected: [],
    notes: ["These findings come from a language model."],
    ...overrides,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const AI_AVAILABLE = {
  available: true,
  provider: "hosted",
  model: "test-model",
  reason: null,
};

const AI_UNAVAILABLE = {
  available: false,
  provider: "none",
  model: "",
  reason: "Set DEVMEMORY_LLM_API_KEY and DEVMEMORY_LLM_MODEL.",
};

function mockApi(handlers: Record<string, () => Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${new URL(String(input)).pathname}`;
    const handler = handlers[key];
    if (handler) return handler();
    if (key === "GET /api/health/ai/status") return json(AI_UNAVAILABLE);
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

async function openHealth() {
  render(<App />);
  await screen.findByText(/disabled Redis caching/);
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "Health" }));
  await user.click(screen.getByRole("button", { name: "Run health check" }));
  return {
    user,
    panel: await screen.findByRole("region", { name: "Memory health check" }),
  };
}

describe("AI-assisted analysis", () => {
  it("says it is not configured instead of pretending to analyse", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(healthReport()),
    });

    const { panel } = await openHealth();

    const ai = within(panel).getByRole("region", { name: "AI-assisted analysis" });
    expect(await within(ai).findByText(/Not configured/)).toBeInTheDocument();
    expect(within(ai).queryByRole("button", { name: "Run AI analysis" })).toBeNull();
    // The deterministic panel still works without a model.
    expect(within(panel).getByText(/no language model was used/)).toBeInTheDocument();
  });

  it("offers the action when a model is configured", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(healthReport()),
      "GET /api/health/ai/status": () => json(AI_AVAILABLE),
    });

    const { panel } = await openHealth();

    const ai = within(panel).getByRole("region", { name: "AI-assisted analysis" });
    expect(
      await within(ai).findByRole("button", { name: "Run AI analysis" }),
    ).toBeInTheDocument();
  });

  it("labels findings as model-generated and says nothing was changed", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(healthReport()),
      "GET /api/health/ai/status": () => json(AI_AVAILABLE),
      "POST /api/health/ai": () => json(aiReport()),
    });

    const { user, panel } = await openHealth();
    const ai = within(panel).getByRole("region", { name: "AI-assisted analysis" });
    await user.click(await within(ai).findByRole("button", { name: "Run AI analysis" }));

    expect(await within(ai).findByText("Model-generated.")).toBeInTheDocument();
    expect(within(ai).getByText(/Nothing was changed/)).toBeInTheDocument();
    expect(within(ai).getByText("model")).toBeInTheDocument();
  });

  it("shows the model's own uncertainty and evidence", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(healthReport()),
      "GET /api/health/ai/status": () => json(AI_AVAILABLE),
      "POST /api/health/ai": () => json(aiReport()),
    });

    const { user, panel } = await openHealth();
    const ai = within(panel).getByRole("region", { name: "AI-assisted analysis" });
    await user.click(await within(ai).findByRole("button", { name: "Run AI analysis" }));

    expect(await within(ai).findByText(/Model's uncertainty/)).toBeInTheDocument();
    expect(within(ai).getByText("We disabled Redis caching")).toBeInTheDocument();
    expect(within(ai).getByText("Merge them into one memory.")).toBeInTheDocument();
  });

  it("lists rejected suggestions rather than hiding them", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(healthReport()),
      "GET /api/health/ai/status": () => json(AI_AVAILABLE),
      "POST /api/health/ai": () =>
        json(
          aiReport({
            findings: [],
            rejected: ["Finding 0: referenced memory id(s) not in the provided set: ghost."],
          }),
        ),
    });

    const { user, panel } = await openHealth();
    const ai = within(panel).getByRole("region", { name: "AI-assisted analysis" });
    await user.click(await within(ai).findByRole("button", { name: "Run AI analysis" }));

    expect(await within(ai).findByText(/Rejected suggestions \(1\)/)).toBeInTheDocument();
  });

  it("reports that memories were withheld from the prompt", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(healthReport()),
      "GET /api/health/ai/status": () => json(AI_AVAILABLE),
      "POST /api/health/ai": () =>
        json(aiReport({ findings: [], excluded_memories: ["evil"] })),
    });

    const { user, panel } = await openHealth();
    const ai = within(panel).getByRole("region", { name: "AI-assisted analysis" });
    await user.click(await within(ai).findByRole("button", { name: "Run AI analysis" }));

    expect(
      await within(ai).findByText(/withheld from the prompt/),
    ).toBeInTheDocument();
  });

  it("shows an actionable error when the model call fails", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(healthReport()),
      "GET /api/health/ai/status": () => json(AI_AVAILABLE),
      "POST /api/health/ai": () =>
        json({ detail: "The model provider returned HTTP 500." }, 502),
    });

    const { user, panel } = await openHealth();
    const ai = within(panel).getByRole("region", { name: "AI-assisted analysis" });
    await user.click(await within(ai).findByRole("button", { name: "Run AI analysis" }));

    expect(await within(ai).findByRole("alert")).toHaveTextContent(
      "returned HTTP 500",
    );
  });

  it("scopes the analysis to the active project filter", async () => {
    const fetchMock = mockApi({
      "GET /api/memories": () => json([memory()]),
      "GET /api/health": () => json(healthReport()),
      "GET /api/health/ai/status": () => json(AI_AVAILABLE),
      "POST /api/health/ai": () => json(aiReport()),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/disabled Redis caching/);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Filter by project" }),
      "payments-api",
    );
    await user.click(screen.getByRole("tab", { name: "Health" }));
    await user.click(screen.getByRole("button", { name: "Run health check" }));

    const panel = await screen.findByRole("region", { name: "Memory health check" });
    const ai = within(panel).getByRole("region", { name: "AI-assisted analysis" });
    await user.click(await within(ai).findByRole("button", { name: "Run AI analysis" }));

    const call = await vi.waitFor(() => {
      // Match the POST only: the status call shares the same path prefix.
      const found = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith("/api/health/ai") && init?.method === "POST",
      );
      if (!found) throw new Error("not called yet");
      return found;
    });
    expect(String(call[1]?.body)).toContain('"project":"payments-api"');
  });
});