import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Memory } from "./types";

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

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

/** Route requests by "METHOD /path" so each test states only what it needs. */
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

const AI_STATUS_MOCK = {
  available: false,
  provider: "none",
  model: "",
  reason: "AI-assisted analysis is not configured.",
};

function mockApi(handlers: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const path = new URL(url).pathname;
    const key = `${method} ${path}`;
    const handler = handlers[key];
    if (!handler) {
      // The retrieval panel loads index status on mount; unrelated tests do not
      // care about it, so answer with a default.
      if (key === "GET /api/health/ai/status") {
        return json(AI_STATUS_MOCK);
      }
      if (key === "GET /api/embeddings/status") {
        return json(DEFAULT_STATUS);
      }
      throw new Error(`Unhandled request in test: ${key}`);
    }
    return handler(url, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("loading, empty and error states", () => {
  it("shows a loading state, then the memories", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });

    render(<App />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading memories…");
    expect(await screen.findByText(/uses PostgreSQL 15/)).toBeInTheDocument();
  });

  it("shows an empty state that points at import", async () => {
    mockApi({ "GET /api/memories": () => json([]) });

    render(<App />);

    expect(await screen.findByText("No memories yet")).toBeInTheDocument();
    expect(screen.getByText(/import a JSON file/)).toBeInTheDocument();
  });

  it("shows the API's message when loading fails, and retries", async () => {
    let attempt = 0;
    mockApi({
      "GET /api/memories": () => {
        attempt += 1;
        return attempt === 1
          ? json({ detail: "Database unavailable" }, 500)
          : json([memory()]);
      },
    });
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Database unavailable",
    );

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText(/uses PostgreSQL 15/)).toBeInTheDocument();
    expect(attempt).toBe(2);
  });

  it("reports an unreachable backend instead of an empty library", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Cannot reach the API/,
    );
  });
});

describe("stats and list", () => {
  it("derives counts from the loaded data", async () => {
    mockApi({
      "GET /api/memories": () =>
        json([
          memory({ id: "a" }),
          memory({ id: "b", project: "analytics" }),
          memory({ id: "c", status: "superseded", superseded_by: "a" }),
        ]),
    });

    render(<App />);

    const stats = await screen.findByRole("list", { name: "Memory totals" });
    expect(within(stats).getByText("Memories").previousSibling).toHaveTextContent("3");
    expect(within(stats).getByText("Projects").previousSibling).toHaveTextContent("2");
    expect(within(stats).getByText("Superseded").previousSibling).toHaveTextContent("1");
  });

  it("filters the visible list by search without another request", async () => {
    const fetchMock = mockApi({
      "GET /api/memories": () =>
        json([
          memory({ id: "a", content: "The user service uses PostgreSQL." }),
          memory({ id: "b", content: "We disabled Redis caching." }),
        ]),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL/);

    await user.type(screen.getByRole("searchbox", { name: "Search memories" }), "redis");

    expect(screen.queryByText(/uses PostgreSQL/)).not.toBeInTheDocument();
    expect(screen.getByText(/disabled Redis caching/)).toBeInTheDocument();
    // One initial load of the list, no extra fetch per keystroke.
    const listCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/api/memories"),
    );
    expect(listCalls).toHaveLength(1);
  });

  it("sends the project filter to the server", async () => {
    const fetchMock = mockApi({ "GET /api/memories": () => json([memory()]) });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL/);

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Filter by project" }),
      "payments-api",
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringContaining("project=payments-api"),
        expect.anything(),
      ),
    );
  });

  it("keeps the other projects selectable while one is filtered", async () => {
    mockApi({
      "GET /api/memories": (url: string) => {
        const project = new URL(url).searchParams.get("project");
        return json(
          project === "payments-api"
            ? [memory()]
            : [
                memory(),
                memory({ id: "mem-2", project: "analytics", content: "Exports run nightly." }),
              ],
        );
      },
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/Exports run nightly/);

    const select = screen.getByRole("combobox", {
      name: "Filter by project",
    }) as HTMLSelectElement;
    await user.selectOptions(select, "payments-api");

    // The server only sent payments-api, but the picker must not hide analytics.
    await waitFor(() =>
      expect([...select.options].map((option) => option.value)).toEqual([
        "",
        "analytics",
        "payments-api",
      ]),
    );
  });
});

describe("create", () => {
  it("adds a memory and shows it in the list", async () => {
    const created = memory({ id: "new-1", content: "Use request IDs everywhere." });
    let listCalls = 0;
    mockApi({
      "GET /api/memories": () => {
        listCalls += 1;
        return json(listCalls === 1 ? [] : [created]);
      },
      "POST /api/memories": () => json(created, 201),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("No memories yet");

    await user.click(screen.getByRole("button", { name: "New memory" }));
    await user.type(screen.getByLabelText("Content"), "Use request IDs everywhere.");
    await user.type(screen.getByLabelText("Project"), "payments-api");
    await user.type(screen.getByLabelText("Source"), "platform-team");
    await user.click(screen.getByRole("button", { name: "Add memory" }));

    expect(await screen.findByText("Memory added.")).toBeInTheDocument();
    // Scoped to the list: the new memory is also auto-selected, so its text
    // appears in the detail panel too.
    const list = screen.getByRole("list", { name: "Memories" });
    expect(await within(list).findByText("Use request IDs everywhere.")).toBeInTheDocument();
  });

  it("surfaces a server validation error and keeps the form open", async () => {
    mockApi({
      "GET /api/memories": () => json([]),
      "POST /api/memories": () =>
        json(
          {
            detail: [
              {
                loc: ["body", "project"],
                msg: "String should have at least 1 character",
              },
            ],
          },
          422,
        ),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("No memories yet");

    await user.click(screen.getByRole("button", { name: "New memory" }));
    await user.type(screen.getByLabelText("Content"), "Something.");
    await user.type(screen.getByLabelText("Project"), "p");
    await user.type(screen.getByLabelText("Source"), "s");
    await user.click(screen.getByRole("button", { name: "Add memory" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("project:");
    expect(screen.getByLabelText("Content")).toBeInTheDocument();
  });

  it("blocks submission while confidence is out of range", async () => {
    mockApi({ "GET /api/memories": () => json([]) });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("No memories yet");

    await user.click(screen.getByRole("button", { name: "New memory" }));
    await user.type(screen.getByLabelText("Content"), "Something.");
    await user.type(screen.getByLabelText("Project"), "p");
    await user.type(screen.getByLabelText("Source"), "s");
    await user.type(screen.getByLabelText(/Confidence/), "1.5");

    expect(screen.getByText(/between 0 and 1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add memory" })).toBeDisabled();
  });
});

describe("detail, edit and delete", () => {
  it("opens a memory's metadata when selected", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /uses PostgreSQL/ }));

    const detail = screen.getByRole("article", { name: "Memory detail" });
    expect(within(detail).getByText("mem-1")).toBeInTheDocument();
    expect(within(detail).getByText("architecture-review")).toBeInTheDocument();
  });

  it("saves an edit and shows the updated content", async () => {
    const updated = memory({ content: "The user service uses PostgreSQL 16." });
    let listCalls = 0;
    mockApi({
      "GET /api/memories": () => {
        listCalls += 1;
        return json(listCalls === 1 ? [memory()] : [updated]);
      },
      "PATCH /api/memories/mem-1": () => json(updated),
    });
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /uses PostgreSQL/ }));
    await user.click(screen.getByRole("button", { name: "Edit" }));

    const content = screen.getByLabelText("Content");
    await user.clear(content);
    await user.type(content, "The user service uses PostgreSQL 16.");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Changes saved.")).toBeInTheDocument();
    expect((await screen.findAllByText(/PostgreSQL 16/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/PostgreSQL 15/)).not.toBeInTheDocument();
  });

  it("requires confirmation before deleting", async () => {
    let listCalls = 0;
    const fetchMock = mockApi({
      "GET /api/memories": () => {
        listCalls += 1;
        return json(listCalls === 1 ? [memory()] : []);
      },
      "DELETE /api/memories/mem-1": () => new Response(null, { status: 204 }),
    });
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /uses PostgreSQL/ }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    // Nothing has been sent yet.
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/memories/mem-1"),
      expect.objectContaining({ method: "DELETE" }),
    );

    await user.click(screen.getByRole("button", { name: "Yes, delete permanently" }));

    expect(await screen.findByText("Memory deleted.")).toBeInTheDocument();
    expect(await screen.findByText("No memories yet")).toBeInTheDocument();
  });

  it("keeps the memory when a delete is refused with 409", async () => {
    mockApi({
      "GET /api/memories": () => json([memory()]),
      "DELETE /api/memories/mem-1": () =>
        json({ detail: "Memory 'mem-1' is named as the replacement by 1 other" }, 409),
    });
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /uses PostgreSQL/ }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete permanently" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "is named as the replacement",
    );
    const list = screen.getByRole("list", { name: "Memories" });
    expect(within(list).getByText(/uses PostgreSQL 15/)).toBeInTheDocument();
  });
});

describe("import", () => {
  it("imports valid JSON and reports the count", async () => {
    let listCalls = 0;
    mockApi({
      "GET /api/memories": () => {
        listCalls += 1;
        return json(listCalls === 1 ? [] : [memory()]);
      },
      "POST /api/memories/import": () => json({ imported: 1, ids: ["mem-1"] }, 201),
    });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("No memories yet");

    await user.click(screen.getByLabelText("JSON"));
    await user.paste(
      JSON.stringify([
        {
          content: "The user service uses PostgreSQL 15 for persistence.",
          category: "decision",
          source: "architecture-review",
          project: "payments-api",
        },
      ]),
    );
    await user.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByText("Imported 1 memories.")).toBeInTheDocument();
  });

  it("reports invalid JSON without calling the API", async () => {
    const fetchMock = mockApi({ "GET /api/memories": () => json([]) });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("No memories yet");

    await user.click(screen.getByLabelText("JSON"));
    await user.paste("{ not json");
    await user.click(screen.getByRole("button", { name: "Import" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Invalid JSON");
    // Only the initial list load; the import never reached the network.
    const listCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/api/memories"),
    );
    expect(listCalls).toHaveLength(1);
  });

  it("rejects a JSON object that is not a memory array", async () => {
    mockApi({ "GET /api/memories": () => json([]) });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("No memories yet");

    await user.click(screen.getByLabelText("JSON"));
    await user.paste('{"memories": "nope"}');
    await user.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Expected a JSON array of memories",
    );
  });
});

describe("tab separation (regression)", () => {
  // Reported bug: after running the health check, clicking "New memory" appeared
  // to do nothing, because the form rendered below a tall analysis panel that
  // shared the same page. Each job now owns a tab, so the editor cannot be
  // pushed off-screen by an analysis panel.
  it("can add a memory after visiting the health tab", async () => {
    let created = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname;
      const method = init?.method ?? "GET";
      if (path === "/api/memories" && method === "GET") {
        return json(
          created
            ? [memory(), memory({ id: "m2", content: "Brand new memory." })]
            : [memory()],
        );
      }
      if (path === "/api/memories" && method === "POST") {
        created = true;
        return json(memory({ id: "m2" }), 201);
      }
      if (path === "/api/health") {
        return json({
          generated_at: "2026-01-01T00:00:00Z",
          analyzer: "deterministic-rules",
          total_memories: 1,
          projects: ["payments-api"],
          summary: {},
          findings: [],
          limitations: [],
        });
      }
      if (path === "/api/embeddings/status") return json(DEFAULT_STATUS);
      if (path === "/api/health/ai/status") return json(AI_STATUS_MOCK);
      throw new Error(`Unhandled: ${method} ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);

    await user.click(screen.getByRole("tab", { name: "Health" }));
    await user.click(screen.getByRole("button", { name: "Run health check" }));
    await screen.findByRole("region", { name: "Memory health check" });

    await user.click(screen.getByRole("tab", { name: "Memories" }));
    await user.click(screen.getByRole("button", { name: "New memory" }));

    // The form is in the visible tab, not buried under the analysis panel.
    const form = screen.getByLabelText("Content").closest("form");
    expect(form).not.toBeNull();
    expect(
      screen.queryByRole("region", { name: "Memory health check" }),
    ).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Content"), "Brand new memory.");
    await user.type(screen.getByLabelText("Project"), "payments-api");
    await user.type(screen.getByLabelText("Source"), "manual");
    await user.click(screen.getByRole("button", { name: "Add memory" }));

    expect(await screen.findByText("Memory added.")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Memories" });
    expect(await within(list).findByText("Brand new memory.")).toBeInTheDocument();
  });

  it("shows only one section at a time", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);

    expect(screen.getByRole("list", { name: "Memories" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Retrieval playground" })).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Retrieval" }));

    expect(screen.getByRole("region", { name: "Retrieval playground" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Memories" })).toBeNull();
  });

  it("opens a memory from another tab and switches back to it", async () => {
    mockApi({ "GET /api/memories": () => json([memory()]) });
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/uses PostgreSQL 15/);
    await user.click(screen.getByRole("tab", { name: "Report" }));
    await screen.findByRole("region", { name: "Inspector report" });

    await user.click(screen.getByRole("tab", { name: "Memories" }));
    await user.click(await screen.findByRole("button", { name: /uses PostgreSQL/ }));

    const detail = screen.getByRole("article", { name: "Memory detail" });
    expect(within(detail).getByText("mem-1")).toBeInTheDocument();
  });
});
