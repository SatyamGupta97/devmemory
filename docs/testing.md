# Testing guide

How to verify each part of DevMemory. Three layers, cheapest first:

| Layer | Command | Catches |
| ----- | ------- | ------- |
| Unit / integration | `pytest` (backend), `npm test` (frontend) | Logic errors, regressions |
| API contract | `scripts/smoke_api.py` | Endpoints behaving differently than documented |
| Wiring | `scripts/check_frontend_wiring.py` | Frontend and backend unable to talk |
| Manual | The checklists below | Anything a machine cannot judge: layout, wording, feel |

Always run the cheap layers first. A failure in `pytest` explains itself; a failure
you find by clicking around costs you far more time.

---

## Backend

```bash
cd backend
source .venv/bin/activate
pytest -v
```

- **71 tests** across storage, CRUD, import, CORS, validation and persistence.
- Works from the repo root too (`backend/.venv/bin/pytest -v`) — `pytest.ini` puts
  `backend/` on `sys.path`.

### Reading a failure

| What you see | What it means |
| ------------ | ------------- |
| `ModuleNotFoundError: No module named 'app'` | You are not in `backend/`, or `pytest.ini` is missing. `configfile: pytest.ini` in the header confirms it was found. |
| `AssertionError: assert [...] == [...]` | Real logic difference. Read the `>` lines: the left side is expected, right side is actual. |
| `IntegrityError: FOREIGN KEY constraint failed` | A delete hit a referencing memory. Should be a `409`, not a crash. |
| `database is locked` | Another process holds the file. `pkill -f "uvicorn app.main"`. |

---

## Frontend

```bash
cd frontend
npm test           # 25 tests
npm run typecheck  # tsc --noEmit
npm run build      # production build
```

### Reading a failure

| What you see | What it means |
| ------------ | ------------- |
| `Found multiple elements with the text: X` | Your query matched in two places. Scope it: `within(screen.getByRole("list", { name: "Memories" }))`. |
| `Unable to find role` | The element is not rendered yet — `await screen.findBy...` instead of `getBy...`. |
| `Unhandled request in test: POST /api/memories` | Your mock is missing that route. Add it to the `mockApi` map. |
| `Cannot find name 'describe'` | Vitest globals are not typed. `types: ["vitest/globals"]` in `tsconfig.json`. |

---

## API contract

With the server running on port 8000:

```bash
python3 scripts/smoke_api.py
```

Covers the whole API surface: CRUD, filters, supersede rules, atomic import,
retrieval and the health check. Uses its own `demo-<random>` project namespace, so it
never touches your real memories. Exit code `0` = pass, `1` = a check failed, `2` =
could not reach the server.

---

## Frontend ↔ backend wiring

With **both** servers running:

```bash
python3 scripts/check_frontend_wiring.py
```

13 checks: the dev server serves the app shell, the API is healthy, the Vite origin is
allowed by CORS, a foreign origin is refused, the PATCH preflight is permitted, and a
memory round-trips. Exits non-zero on failure.

This is the layer that catches the mistake that unit tests cannot see: the frontend
and backend both work perfectly and still cannot talk, because of a CORS or port
mismatch.

---

# Manual checklist — Memory Explorer (Phase 3)

Automated tests cannot tell you the page looks wrong. This can.

Start the backend, start the frontend, open <http://localhost:5173>.

### Setup

- [ ] Open <http://localhost:5173>. The page loads with a header reading **DevMemory**,
      a tagline, and a stats row reading `0 / 0 / 0 / 0`.
- [ ] The list area shows **"No memories yet."** with a hint about importing a file.
- [ ] The right-hand panel shows **"Select a memory to inspect its metadata…"** and the
      import form.

### Load data

- [ ] **Import memories** → **Load file…** → choose `data/sample_memories.json` →
      **Import**.
- [ ] A green banner: **"Imported 14 memories."**
- [ ] The stats row updates to `14 / 2 / 14 / 0` (memories / projects / active /
      superseded).
- [ ] The list shows 14 cards, each with a category badge, a project name, the
      content, and a source line.

### Search

- [ ] Type `redis` in the search box → the list narrows to the two Redis memories.
      No spinner, no delay.
- [ ] Type `something that matches nothing` → **"No memories match…"** with a
      **Clear search** link. Clicking it restores all 14.
- [ ] The search box is labelled and reachable by keyboard (Tab).

### Filter

- [ ] Select project **analytics** → the list narrows to 6 rows. The API is called
      (visible in the Network tab).
- [ ] Select category **decision** on top → 4 rows.
- [ ] Set both to **All** → 14 rows return.

### Inspect

- [ ] Click a card → the right panel shows the full content, and a metadata grid:
      Category, Project, Source, Confidence, Status, Superseded by, Created, Updated,
      and the UUID.
- [ ] The selected card is visually highlighted.
- [ ] Click a second card → the panel updates to that memory.

### Add

- [ ] **New memory** → the form appears with empty fields.
- [ ] Type a content, pick a category, type a project and a source → **Add memory**
      becomes enabled.
- [ ] Clear the content field → the button is disabled again.
- [ ] Type `1.5` in Confidence → a red message **"Use a number between 0 and 1, or
      leave empty."** and the button stays disabled.
- [ ] Enter valid values → **Add memory** → green banner **"Memory added."**, the new
      memory is selected, and the count goes to 15.

### Edit

- [ ] With a memory selected, click **Edit** → the form is pre-filled with its values.
- [ ] Change the content → **Save changes** → green banner **"Changes saved."** and
      the card and detail both show the new text.
- [ ] Click **Cancel** → the form closes without changes.

### Delete

- [ ] Click **Delete** → the button is replaced by **"This cannot be undone."** and
      **"Yes, delete permanently"**. Nothing has been deleted yet.
- [ ] Click **Cancel** → the normal buttons return, memory still there.
- [ ] Click **Delete** then **"Yes, delete permanently"** → green banner **"Memory
      deleted."**, the card disappears, the count drops by one.

### Error states — the important ones

- [ ] **Stop the backend** (Ctrl+C in the API terminal).
- [ ] Reload the page → a **red** banner: *"Cannot reach the API at
      http://127.0.0.1:8000. Is the backend running?"* — and a **Retry** button.
      It must **not** look like an empty library.
- [ ] Start the backend again → click **Retry** → the list loads normally.

- [ ] With the backend running, create a memory that another memory supersedes
      (see the API section of the README), then try to delete the replacement from
      the UI → a red banner naming the blocking memory, and the memory is still
      there. It must not vanish.

### Import errors

- [ ] Paste `{ not json` into the import box → **Import** → a red message
      **"Invalid JSON: …"**. Nothing is sent to the server.
- [ ] Paste `{"memories": "nope"}` → red message **"Expected a JSON array of
      memories…"**.
- [ ] Paste a valid array where one entry has `"content": ""` → the API rejects the
      whole batch with a message naming the field, and the count does **not** change.

### Responsiveness

- [ ] Narrow the window below ~860px → the two columns stack into one.
- [ ] Below ~560px → the form rows and the metadata grid become a single column.
- [ ] No horizontal scrolling at any width.

### Accessibility spot-check

- [ ] Tab through the page → focus is always visible.
- [ ] Errors are announced (they use `role="alert"`).
- [ ] The delete confirmation is reachable by keyboard and can be dismissed with
      Escape… if it does not close, note it — that is a real gap to fix.

---

# Manual checklist — Memory Health Check (Phase 4)

Automated tests confirm the rules fire on the data they were written for. These
steps confirm the findings are *legible* — that a developer can read a finding and
understand what to do, without reading the source.

With the backend and frontend running, open <http://localhost:5173> and load
`data/sample_memories.json` first.

### Run it

- [ ] Click **Run health check** → a panel appears below the toolbar.
- [ ] The panel says `Analyzer: deterministic-rules — no language model was used.`
      This wording matters: the user must know whether a model was involved.
- [ ] The summary row shows counts by type (exact duplicate, potential
      contradiction, potentially stale, and so on).

### Read a finding

- [ ] Each finding has a severity badge (High / Medium / Low / Info) and a
      coloured left border.
- [ ] Click **Evidence (n)** → it expands to show the actual memory contents
      that triggered the finding, with their ids and namespaces.
- [ ] Every finding has a **Suggested action**.
- [ ] Contradiction findings also show an **Uncertainty** note explaining that a
      contradiction is a candidate, not a verdict.

### Check the expected findings against the sample data

With `data/sample_memories.json` loaded, the summary should show roughly:

| Issue type | Expected | Why |
| ---------- | -------- | --- |
| `exact_duplicate` | 1 | "The user service uses PostgreSQL 15…" appears twice |
| `near_duplicate` | 1 | The two Redis-caching memories |
| `potential_contradiction` | 3 | PostgreSQL vs MySQL, Celery vs Dramatiq, Python 3.8 vs 3.11 |
| `potentially_stale` | ~7 | The deliberately old entries |
| `unreliable_source` | ~4 | `chat`, `old-wiki-page`, `eng-blog-draft`, `legacy-platform-doc` |
| `suspicious_content` | 1 | The "Ignore all previous instructions…" memory |

- [ ] Click a memory id under **Affected memories** → that memory is selected in
      the detail panel, so you can check the evidence yourself.
- [ ] Open **What this check cannot tell you** → the limitations are listed.

### Confirm it is read-only

- [ ] Note the memory count in the stats row.
- [ ] Run the health check three times.
- [ ] The count is unchanged, and no memory was edited or deleted.
- [ ] Restart the backend — the same findings come back.

### Project scope

- [ ] Set the project filter to `analytics`, then run the health check.
- [ ] The panel says `7 memories checked across 1 project` and every finding
      refers only to `analytics` memories.

### The case worth checking by hand

- [ ] Find the **Potential contradiction** covering the PostgreSQL/MySQL pair.
- [ ] It lists **three** memory ids, not two: the two duplicate memories and the
      MySQL one. One underlying problem should be one finding.
- [ ] The evidence shows all three contents.

---

# Manual checklist — Embeddings and Semantic Retrieval (Phase 6)

Automated tests cover the provider abstraction, vector storage and the API. These steps
confirm the honest labelling is visible to a *user* — that nobody can mistake the local
provider for a semantic model.

Both servers running, `data/sample_memories.json` imported.

### Index state

- [ ] In the retrieval playground, the **Embedding index** box shows
      `Provider local · model hashed-ngrams-1024 · 1024 dimensions`.
- [ ] It reads `0 of 19 memories indexed` and `19 need indexing`.
- [ ] A yellow warning reads *"This provider compares surface form, not meaning."*
      This wording is the point of the phase — do not let it be buried.
- [ ] The button offers both **Index memories** and **Re-index everything**.

### Build the index

- [ ] Click **Index memories** → `Indexed 19, skipped 0 already current.`
- [ ] The coverage line updates to `19 of 19 memories indexed`.
- [ ] The "need indexing" warning disappears.
- [ ] Click **Index memories** again → `Indexed 0, skipped 19 already current.`
      Incremental indexing works.
- [ ] Edit a memory, then re-open the panel (or click Index again) → exactly
      `1 need indexing`.

### Compare the strategies

- [ ] Set strategy to **Keyword (BM25)**, enter `Add caching to the user service.`,
      click **Retrieve**. Note the rank of the Redis-caching memory.
- [ ] Switch to **Semantic**, retrieve again.
- [ ] Each result shows its **method** badge (`keyword-bm25` or
      `semantic-embedding`), so you can tell which run produced it.
- [ ] **Expected and honest:** the two lists are the same memories in the same
      order. The local provider does not beat BM25 on this dataset. If a demo
      implies otherwise, it is wrong.

### Semantic without an index

- [ ] Delete `backend/devmemory.db`, restart the backend, re-import the sample data,
      and retrieve with strategy **Semantic** before indexing.
- [ ] A red error explains that no embeddings are indexed and names
      `POST /api/embeddings/index` — it must **not** look like "nothing matched".

### With a hosted model (optional)

Only if you have a key. This is the step that proves semantic retrieval works.

- [ ] `export DEVMEMORY_EMBEDDING_API_KEY=... DEVMEMORY_EMBEDDING_MODEL=text-embedding-3-small`
- [ ] Restart the backend → the panel shows `Provider hosted` and **no** warning.
- [ ] Click **Re-index everything** → the index is rebuilt for the new provider.
- [ ] Retrieve on **Semantic** → the Redis-caching memory should climb above the
      database decisions, and the explanation should say the provider compares meaning.

If that does not happen, the ranking failure is real and the benchmark (Phase 7) will
measure it rather than hide it.

---

# Manual checklist — Retrieval Benchmark (Phase 7)

The point of this phase is that numbers must be *earned*. These steps check that the UI
shows where each number came from and admits what it cannot prove.

Backend and frontend running, `data/sample_memories.json` imported, vectors indexed.

### Run it

- [ ] Click **Benchmark** in the toolbar → the panel opens.
- [ ] It states `10 version-controlled queries, cut-off k=5` and mentions that ground
      truth is content-matched so it survives re-importing.
- [ ] Before running, it says a ranking can "only be admired, not evaluated".

### One strategy

- [ ] Click **Run keyword** → metrics appear: precision@5 `0.727`, recall@5 `0.833`,
      MRR `0.806`, 2 memories missed, 7 irrelevant returned.
- [ ] The table lists all ten queries, each with its own P@k, R@k and RR.
- [ ] Rows with a miss name the missed memory, not just a count.

### Both strategies

- [ ] Click **Compare keyword vs semantic** → two columns appear side by side.
- [ ] Semantic shows precision `0.660`, recall `0.944`, MRR `0.917`.
- [ ] The table gains a `P@k (sem)` and `R@k (sem)` column.
- [ ] **Notice the direction of the trade:** recall and MRR improve, precision and
      irrelevant-results get worse. If a demo claims semantic is simply better, it is
      misreading this table.

### Honesty checks

- [ ] Open **What these numbers do and do not prove** → the ten-query limitation is
      stated.
- [ ] The `q10-unrelated` row shows recall `—` rather than `0.00`, because there was
      nothing to recall.
- [ ] Run the benchmark twice → identical numbers. Results are reproducible.

### Failure paths

- [ ] Delete `backend/devmemory.db`, restart the backend, then run the benchmark with no
      memories imported → the report says no query could be scored and names
      `data/sample_memories.json`.
- [ ] Run **Run semantic** without indexing → a red message names
      `POST /api/embeddings/index`; the keyword numbers, if already run, stay on screen.

### The claim worth testing yourself

- [ ] Open `data/benchmark.json` and reword one expected memory's `content` by a word.
- [ ] Run `pytest tests/test_benchmark.py -k resolves` → it fails, telling you the
      benchmark no longer matches the sample data. Silent loss of ground truth is the
      failure mode this test exists to prevent.

---

## How to report a failure

Please include:

1. **The step** — which checkbox failed.
2. **What you saw** — the exact text, not a paraphrase. Copy the banner verbatim.
3. **What you expected** — from this checklist.
4. **The console output** — press F12, go to the Console tab, copy any red errors.
   For a network failure, the Network tab shows the request and its status.

That is enough to fix it without guessing.
