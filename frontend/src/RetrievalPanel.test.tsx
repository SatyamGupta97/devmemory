import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Memory, RetrievalResult } from "./types";

function memory(overrides: Partial<Memory> = {}): Memory {
  return {
    id: "mem-1",
    content:
      "We disabled Redis caching for user records because stale cache entries caused wrong account balances.",
    category: "failure",
    source: "incident-142",
    project: "payments-api",
    created_at: "2025-11-02T09:00:00Z",
    updated_at: "2025-11-02T09:00:00Z",
    confidence: 0.95,
    status: "active",
    superseded_by: null,
    ...overrides,
  };
}

function retrieval(overrides: Partial<RetrievalResult> = {}): RetrievalResult {
  return {
    query: "add caching to the user service",
    strategy: "keyword-bm25",
    project: null,
    considered: 2,
    returned: 1,
    matches: [
      {
        memory: memory(),
        score: 1.88,
        matched_terms: [
          { term: "caching", idf: 1.18, term_frequency: 1, contribution: 1.18 },
          { term: "user", idf: 0.55, term_frequency: 1, contribution: 0.7 },
        ],
        explanation:
          "Matched 2 of 4 query term(s): caching (x1), user (x1). Largest contribution from 'caching' (idf 1.18).",
      },
    ],
    unmatched_query_terms: ["add"],
    notes: [
      "Keyword matching only: a memory that means the same thing in different words scores zero and is never returned.",
      "Scores are relevance ranks, not probabilities. A score of 4.1 does not mean the memory is right 4.1 times out of 10, or that it is correct at all.",
      "Scores are only comparable within a single query.",
      "Superseded memories are included and labelled.",
    ],
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
    if (!handler) throw new Error(`Unhandled request in test: ${key}`);
    return handler();
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function openPlayground() {
  render(<App />);
  await screen.findByText(/disabled Redis caching/);
  return screen.getByRole("region", { name: "Retrieval playground" });
}

describe("retrieval playground", () => {
  it("is visible without running anything", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });

    const panel = await openPlayground();

    expect(within(panel).getByLabelText("Coding task")).toBeInTheDocument();
    expect(
      within(panel).getByText(/ranked by keyword relevance/),
    ).toBeInTheDocument();
  });

  it("does not allow an empty query to be submitted", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });

    const panel = await openPlayground();

    expect(within(panel).getByRole("button", { name: "Retrieve" })).toBeDisabled();
  });

  it("shows ranked matches with their scores and matched terms", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/retrieve": () => json(retrieval()),
    });
    const user = userEvent.setup();

    const panel = await openPlayground();
    await user.type(within(panel).getByLabelText("Coding task"), "add caching");
    await user.click(within(panel).getByRole("button", { name: "Retrieve" }));

    const list = await within(panel).findByRole("list", { name: "Ranked memories" });
    expect(within(list).getByText("#1")).toBeInTheDocument();
    expect(within(list).getByText("score 1.880")).toBeInTheDocument();
    expect(within(list).getByText("caching")).toBeInTheDocument();
    expect(within(list).getByText(/Largest contribution from/)).toBeInTheDocument();
  });

  it("reports which query terms matched nothing", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/retrieve": () => json(retrieval()),
    });
    const user = userEvent.setup();

    const panel = await openPlayground();
    await user.type(within(panel).getByLabelText("Coding task"), "add caching");
    await user.click(within(panel).getByRole("button", { name: "Retrieve" }));

    expect(
      await within(panel).findByText(/Ignored terms that matched no memory: add/),
    ).toBeInTheDocument();
  });

  it("explains the lexical limitation when nothing matches", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/retrieve": () =>
        json(
          retrieval({
            matches: [],
            returned: 0,
            considered: 2,
            unmatched_query_terms: ["add", "caching"],
          }),
        ),
    });
    const user = userEvent.setup();

    const panel = await openPlayground();
    await user.type(within(panel).getByLabelText("Coding task"), "add caching");
    await user.click(within(panel).getByRole("button", { name: "Retrieve" }));

    expect(
      await within(panel).findByText(/No memory shares a word with this task/),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/known limitation of this baseline/)).toBeInTheDocument();
  });

  it("states that the scores are not probabilities", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/retrieve": () => json(retrieval()),
    });
    const user = userEvent.setup();

    const panel = await openPlayground();
    await user.type(within(panel).getByLabelText("Coding task"), "add caching");
    await user.click(within(panel).getByRole("button", { name: "Retrieve" }));
    await within(panel).findByRole("list", { name: "Ranked memories" });

    await user.click(within(panel).getByText("What this ranking cannot tell you"));

    expect(within(panel).getByText(/not probabilities/)).toBeInTheDocument();
  });

  it("passes the active project filter to the request", async () => {
    const fetchMock = mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/retrieve": () => json(retrieval()),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/disabled Redis caching/);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Filter by project" }),
      "payments-api",
    );

    const panel = screen.getByRole("region", { name: "Retrieval playground" });
    await user.type(within(panel).getByLabelText("Coding task"), "caching");
    await user.click(within(panel).getByRole("button", { name: "Retrieve" }));

    const call = fetchMock.mock.calls.find(
      ([url]) => String(url).includes("/api/retrieve"),
    );
    expect(call).toBeDefined();
    expect(String(call![1]?.body)).toContain('"project":"payments-api"');
  });

  it("marks a superseded memory in the results", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/retrieve": () =>
        json(
          retrieval({
            matches: [
              {
                memory: memory({
                  status: "superseded",
                  superseded_by: "mem-9",
                }),
                score: 1.2,
                matched_terms: [
                  { term: "celery", idf: 1.0, term_frequency: 1, contribution: 1.0 },
                ],
                explanation: "Matched 1 of 1 query term(s): celery (x1).",
              },
            ],
          }),
        ),
    });
    const user = userEvent.setup();

    const panel = await openPlayground();
    await user.type(within(panel).getByLabelText("Coding task"), "celery");
    await user.click(within(panel).getByRole("button", { name: "Retrieve" }));

    const list = await within(panel).findByRole("list", { name: "Ranked memories" });
    expect(within(list).getByText("superseded")).toBeInTheDocument();
  });

  it("opens a memory from the results", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/retrieve": () => json(retrieval()),
    });
    const user = userEvent.setup();

    const panel = await openPlayground();
    await user.type(within(panel).getByLabelText("Coding task"), "caching");
    await user.click(within(panel).getByRole("button", { name: "Retrieve" }));
    await user.click(
      within(await within(panel).findByRole("list", { name: "Ranked memories" }))
        .getByRole("button", { name: "Open this memory" }),
    );

    const detail = screen.getByRole("article", { name: "Memory detail" });
    expect(within(detail).getByText("mem-1")).toBeInTheDocument();
  });

  it("shows the server's rejection of a meaningless query", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "POST /api/retrieve": () =>
        json({ detail: "The query contains no searchable terms." }, 422),
    });
    const user = userEvent.setup();

    const panel = await openPlayground();
    await user.type(within(panel).getByLabelText("Coding task"), "the and is");
    await user.click(within(panel).getByRole("button", { name: "Retrieve" }));

    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      "no searchable terms",
    );
  });
});