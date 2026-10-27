import { useCallback, useEffect, useMemo, useState } from "react";
import {
  API_BASE_URL,
  createMemory,
  deleteMemory,
  describeError,
  getHealthReport,
  importMemories,
  listMemories,
  updateMemory,
} from "./api/client";
import { HealthPanel } from "./components/HealthPanel";
import { ImportPanel } from "./components/ImportPanel";
import { MemoryDetail } from "./components/MemoryDetail";
import { MemoryForm } from "./components/MemoryForm";
import { MemoryList } from "./components/MemoryList";
import { RetrievalPanel } from "./components/RetrievalPanel";
import { StatsBar } from "./components/StatsBar";
import { StatusMessage } from "./components/StatusMessage";
import type {
  HealthReport,
  Memory,
  MemoryCategory,
  MemoryCreateInput,
  MemoryUpdateInput,
} from "./types";

type Mode = "browse" | "create" | "edit";

export default function App() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("browse");
  const [busy, setBusy] = useState(false);

  const [healthReport, setHealthReport] = useState<HealthReport | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<"" | MemoryCategory>("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      // Filters are applied by the server, not in the browser: the API is the
      // source of truth, and a client-side filter would disagree with it as soon
      // as pagination exists.
      const data = await listMemories({
        project: projectFilter || undefined,
        category: categoryFilter || undefined,
      });
      setMemories(data);
    } catch (error) {
      setMemories([]);
      setLoadError(describeError(error));
    } finally {
      setLoading(false);
    }
  }, [projectFilter, categoryFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const projects = useMemo(
    () => [...new Set(memories.map((memory) => memory.project))].sort(),
    [memories],
  );

  const visibleMemories = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return memories;
    // Search is client-side so typing feels instant; it filters the rows already
    // loaded rather than issuing a request per keystroke.
    return memories.filter((memory) =>
      [memory.content, memory.source, memory.project, memory.category]
        .join(" ")
        .toLowerCase()
        .includes(term),
    );
  }, [memories, search]);

  const selected = useMemo(
    () => memories.find((memory) => memory.id === selectedId) ?? null,
    [memories, selectedId],
  );

  const runAction = async (action: () => Promise<void>) => {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      await action();
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = (values: MemoryCreateInput) =>
    runAction(async () => {
      const created = await createMemory(values);
      setMode("browse");
      setSelectedId(created.id);
      await load();
      // Be explicit when the active filter hides the new row, otherwise it looks
      // like the save silently failed.
      setNotice(
        projectFilter && projectFilter !== created.project
          ? `Added to project "${created.project}". The current project filter hides it.`
          : "Memory added.",
      );
    });

  const handleUpdate = (values: MemoryUpdateInput) =>
    runAction(async () => {
      if (!selectedId) return;
      await updateMemory(selectedId, values);
      setMode("browse");
      await load();
      setNotice("Changes saved.");
    });

  const handleDelete = () =>
    runAction(async () => {
      if (!selectedId) return;
      await deleteMemory(selectedId);
      setSelectedId(null);
      setMode("browse");
      await load();
      setNotice("Memory deleted.");
    });

  const handleImport = (entries: MemoryCreateInput[]) =>
    runAction(async () => {
      const result = await importMemories(entries);
      await load();
      setNotice(`Imported ${result.imported} memories.`);
    });

  const runHealthCheck = async () => {
    setHealthLoading(true);
    setHealthError(null);
    try {
      // Scoped with the same project filter as the list, so every id in the
      // report refers to a memory that is actually on screen.
      const report = await getHealthReport(projectFilter || undefined);
      setHealthReport(report);
    } catch (error) {
      setHealthError(describeError(error));
    } finally {
      setHealthLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>DevMemory</h1>
          <p className="tagline">
            Memory debugger and quality evaluator for coding agents
          </p>
        </div>
        <span className="api-indicator" title="API base URL">
          API: <code>{API_BASE_URL}</code>
        </span>
      </header>

      <StatsBar memories={memories} />

      {loadError && (
        <StatusMessage tone="error" onDismiss={() => setLoadError(null)}>
          {loadError}{" "}
          <button type="button" className="link" onClick={() => void load()}>
            Retry
          </button>
        </StatusMessage>
      )}
      {actionError && (
        <StatusMessage tone="error" onDismiss={() => setActionError(null)}>
          {actionError}
        </StatusMessage>
      )}
      {notice && (
        <StatusMessage tone="success" onDismiss={() => setNotice(null)}>
          {notice}
        </StatusMessage>
      )}

      <div className="toolbar">
        <input
          type="search"
          placeholder="Search loaded memories…"
          aria-label="Search memories"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />

        <select
          aria-label="Filter by project"
          value={projectFilter}
          onChange={(event) => setProjectFilter(event.target.value)}
        >
          <option value="">All projects</option>
          {projects.map((project) => (
            <option key={project} value={project}>
              {project}
            </option>
          ))}
        </select>

        <select
          aria-label="Filter by category"
          value={categoryFilter}
          onChange={(event) =>
            setCategoryFilter(event.target.value as "" | MemoryCategory)
          }
        >
          <option value="">All categories</option>
          {["decision", "constraint", "failure", "convention", "fact"].map(
            (category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ),
          )}
        </select>

        <button
          type="button"
          className="button button-primary"
          onClick={() => setMode(mode === "create" ? "browse" : "create")}
        >
          {mode === "create" ? "Close" : "New memory"}
        </button>

        <button
          type="button"
          className="button"
          onClick={() => void runHealthCheck()}
          disabled={healthLoading}
        >
          {healthLoading ? "Checking…" : "Run health check"}
        </button>
      </div>

      {healthError && (
        <StatusMessage tone="error" onDismiss={() => setHealthError(null)}>
          {healthError}
        </StatusMessage>
      )}

      {healthReport && (
        <HealthPanel
          report={healthReport}
          onSelectMemory={(id) => {
            setSelectedId(id);
            setMode("browse");
          }}
        />
      )}

      <div className="layout">
        <section className="panel" aria-label="Memory list panel">
          {mode === "create" && (
            <MemoryForm
              busy={busy}
              onSubmit={handleCreate}
              onCancel={() => setMode("browse")}
            />
          )}

          {loading ? (
            <p className="placeholder" role="status">
              Loading memories…
            </p>
          ) : visibleMemories.length === 0 ? (
            <div className="placeholder">
              {memories.length === 0 ? (
                <>
                  <p>No memories yet.</p>
                  <p className="hint">
                    Add one, or import a JSON file below to get started.
                  </p>
                </>
              ) : (
                <p>
                  No memories match “{search}”.{" "}
                  <button
                    type="button"
                    className="link"
                    onClick={() => setSearch("")}
                  >
                    Clear search
                  </button>
                </p>
              )}
            </div>
          ) : (
            <MemoryList
              memories={visibleMemories}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                setMode("browse");
              }}
            />
          )}
        </section>

        <section className="panel" aria-label="Detail panel">
          {mode === "edit" && selected ? (
            <MemoryForm
              initial={selected}
              busy={busy}
              onSubmit={(values) => void handleUpdate(values)}
              onCancel={() => setMode("browse")}
            />
          ) : selected ? (
            <MemoryDetail
              memory={selected}
              busy={busy}
              onEdit={() => setMode("edit")}
              onDelete={() => void handleDelete()}
            />
          ) : (
            <p className="placeholder">
              Select a memory to inspect its metadata, edit it, or delete it.
            </p>
          )}

          <RetrievalPanel
            projectFilter={projectFilter}
            onSelectMemory={(id) => {
              setSelectedId(id);
              setMode("browse");
            }}
          />

          <ImportPanel busy={busy} onImport={(entries) => void handleImport(entries)} />
        </section>
      </div>
    </div>
  );
}
