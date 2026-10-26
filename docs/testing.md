# Testing guide

How to verify each part of DevMemory. Three layers, cheapest first:

| Layer | Command | Catches |
| ----- | ------- | ------- |
| Unit / integration | `pytest` (backend), `npm test` (frontend) | Logic errors, regressions |
| API contract | `scripts/smoke_phase2.py` | Endpoints behaving differently than documented |
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
python3 scripts/smoke_phase2.py
```

28 checks over the whole API surface. Uses its own `demo-<epoch>` project namespace,
so it never touches your real memories. Exit code `0` = pass, `1` = a check failed,
`2` = could not reach the server.

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

## How to report a failure

Please include:

1. **The step** — which checkbox failed.
2. **What you saw** — the exact text, not a paraphrase. Copy the banner verbatim.
3. **What you expected** — from this checklist.
4. **The console output** — press F12, go to the Console tab, copy any red errors.
   For a network failure, the Network tab shows the request and its status.

That is enough to fix it without guessing.
