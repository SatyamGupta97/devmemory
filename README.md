# DevMemory

**Memory debugger and quality evaluator for coding agents.**

Coding agents rely on stored project context: past decisions, constraints, and debugging
history. That memory can go wrong — duplicates pile up, two decisions contradict each
other, old decisions never get retired, and retrieval silently misses the memory that
would have prevented a repeated mistake.

DevMemory is a standalone developer tool that inspects a collection of agent memories,
detects quality problems, tests retrieval quality, and explains *why* a memory was
retrieved for a given coding task.

> Not another general-purpose chatbot. An experimental, evidence-based debugging tool.

## Status

Phase 3 complete: a React UI covers the full memory lifecycle — browse, search, filter,
inspect, add, edit, delete, and JSON import — against the live API.

## Repository layout

```
devmemory/
  backend/            FastAPI service
    app/
      main.py         API entrypoint, startup/lifespan
      config.py       Environment-driven settings
      db.py           SQLite connection + schema
      schemas.py      Pydantic request/response models
      api/            HTTP routers
      services/       Business logic
    tests/            pytest suite
    requirements.txt
    .env.example
  frontend/           React + Vite + TypeScript UI
    src/
      App.tsx         page state and orchestration
      api/client.ts   typed HTTP client, single place for errors
      components/     presentational components
      types.ts        mirrors the backend schemas
    .env.example
  data/
    sample_memories.json
  scripts/
    smoke_phase2.py              end-to-end API checks
    check_frontend_wiring.py     frontend <-> backend integration checks
  docs/
    testing.md                   test guide and manual checklists
  pytest.ini
  .gitignore
  README.md
```

`docs/` arrives with the final write-up.

## Requirements

- Python 3.11+
- Git

## Setup

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Testing

See **[docs/testing.md](docs/testing.md)** for the full guide: how to run each layer
(backend tests, frontend tests, API smoke test, wiring check) and a step-by-step manual
checklist for the Memory Explorer UI.

```bash
# backend
cd backend && source .venv/bin/activate && pytest -v

# frontend
cd frontend && npm test && npm run typecheck

# API contract, with the server running
python3 scripts/smoke_phase2.py

# frontend <-> backend wiring, with both running
python3 scripts/check_frontend_wiring.py
```

## Run the app

Two processes: the API and the UI. Start the API first (the UI fails loudly, and
explains why, if it cannot reach it).

**Terminal 1 — API**

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- Health check: <http://127.0.0.1:8000/health>
- Interactive API docs: <http://127.0.0.1:8000/docs>

**Terminal 2 — UI**

```bash
cd frontend
npm install          # first time only
npm run dev
```

Open <http://localhost:5173>. To start with demo data, use *Import memories* in the UI
and load `data/sample_memories.json`.

If the API runs somewhere other than `http://127.0.0.1:8000`, copy
`frontend/.env.example` to `frontend/.env.local` and set `VITE_API_BASE_URL`.

### Frontend tests, typecheck and build

```bash
cd frontend
npm test          # Vitest + React Testing Library
npm run typecheck
npm run build
```

## Run the tests

```bash
cd backend
source .venv/bin/activate
pytest -v
```

Tests also run from the repository root (`backend/.venv/bin/pytest -v`). The shared
configuration lives in `pytest.ini`, which puts `backend/` on `sys.path` so test modules
can import the service as `from app.main import app`.

## Environment variables

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DEVMEMORY_DB_PATH` | `backend/devmemory.db` | SQLite file location. Tests point this at a temp file. |
| `DEVMEMORY_CORS_ORIGINS` | Vite dev server origins | Comma-separated browser origins allowed to call the API. |

Frontend variables must be prefixed `VITE_` to reach the browser, so never put secrets here:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Where the UI looks for the API |

Model provider settings arrive in a later phase. Nothing is required today, and the app
must remain usable without any model access.

### CORS

A browser blocks a page on `localhost:5173` from reading a response from
`localhost:8000` unless the server opts in. `DEVMEMORY_CORS_ORIGINS` is an explicit
allow-list, never `*`, because a wildcard lets any page on the internet read this API's
responses. Deploying the UI means adding its origin to that list.

CORS is not authentication: it constrains browsers, not other clients.

## API

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/health` | Liveness check |
| `POST` | `/api/memories` | Add a memory (`201`) |
| `GET` | `/api/memories` | List memories, newest first |
| `POST` | `/api/memories/import` | Import a batch atomically (`201`) |
| `GET` | `/api/memories/{id}` | Fetch one memory, or `404` |
| `PATCH` | `/api/memories/{id}` | Partial update |
| `DELETE` | `/api/memories/{id}` | Delete (`204`), `404` if absent, `409` if referenced |

`GET /api/memories` accepts `project` and `category` query filters. Unknown values
return an empty list for `project`; an invalid `category` returns `422`.

Add a memory:

```bash
curl -X POST http://127.0.0.1:8000/api/memories \
  -H 'Content-Type: application/json' \
  -d '{
    "content": "We disabled Redis caching for user records because stale entries caused wrong balances.",
    "category": "failure",
    "source": "incident-142",
    "project": "payments-api",
    "confidence": 0.95
  }'
```

Import a batch:

```bash
# wrap the array: the endpoint takes {"memories": [...]}
python3 -c "import json;print(json.dumps({'memories': json.load(open('../data/sample_memories.json'))}))" \
  | curl -X POST http://127.0.0.1:8000/api/memories/import \
      -H 'Content-Type: application/json' --data-binary @-
```

The batch is **all-or-nothing**: `{"memories": [...]}` is validated entry by entry, and a
single bad row rejects the whole request with `422` before anything is written. A partial
import would leave the user unable to tell what landed, and re-importing would duplicate
it. Batches are capped at 500 entries.

Partial update:

```bash
curl -X PATCH http://127.0.0.1:8000/api/memories/<id> \
  -H 'Content-Type: application/json' \
  -d '{"status": "superseded", "superseded_by": "<newer-id>"}'
```

Memory fields: `content`, `category` (`decision` | `constraint` | `failure` |
`convention` | `fact`), `source`, `project`, optional `confidence` (0–1). The server
assigns `id`, `created_at`, `updated_at`, `status`, and `superseded_by`.

### Supersede rules

Old decisions are preserved, never rewritten. `PATCH` enforces:

- `superseded_by` must point at an existing memory, and not at itself.
- Setting `superseded_by` requires `status: "superseded"`.
- Reactivating (`status: "active"`) requires clearing `superseded_by` to `null`.
- Deleting a memory that another memory names as its replacement returns `409` and lists
  the blocking memory. Nothing is silently unlinked.

### Status codes

| Code | Meaning here |
| ---- | ------------ |
| `201` | memory or batch created |
| `204` | deleted, empty body |
| `404` | no memory with that id |
| `409` | the change would break a link between memories |
| `422` | body parsed but is invalid, or conflicts with a stored-data rule |

Invalid input returns `422` with the offending field named. Blank or whitespace-only
content is rejected by both Pydantic and a SQLite `CHECK` constraint.

## Sample data

`data/sample_memories.json` holds 14 memories across two projects, seeded with the
problems later phases detect: an exact duplicate, a near-duplicate, a contradictory
database decision, a superseded-vs-current queue decision, missing metadata, and a stale
runtime constraint. A test asserts it always validates against the API schema.

## UI architecture notes

- **`api/client.ts` is the only place that calls `fetch`.** `fetch` does not reject on
  4xx/5xx, so every response is checked explicitly, and a network failure (no response at
  all) is reported differently from an HTTP error.
- **Filters go to the server; search stays in the browser.** Server filters will still be
  correct when pagination arrives; search filters the rows already loaded so typing is
  instant and does not fire a request per keystroke.
- **After every mutation the list is re-fetched** instead of being patched locally. The
  server stays the single source of truth; at this scale the extra request is free.
- **Loading, empty, search-miss, and error are four distinct states**, not one spinner.
  An empty library and a failed request look completely different to the user.

## Data model notes

- **SQLite, raw `sqlite3`** — one table, simple queries. An ORM would add a dependency and
  a second description of the same columns without removing work yet.
- **Text timestamps in UTC** — SQLite has no datetime type; ISO 8601 in UTC sorts
  correctly as a string. Microsecond precision is kept so same-second writes stay
  orderable.
- **`project`** — the namespace that makes contradiction detection honest: "user service
  uses MySQL" and "user service uses PostgreSQL" may both be true in different projects.
- **`status` / `superseded_by`** — the schema carries these now because preserving
  historical decisions is a core product principle, but nothing writes them until a
  feature needs to. The API returns them read-only.
- **Storage does not normalise content.** Lowercasing, trimming punctuation and
  similarity scoring belong to the analysis layer, so its rules can change without
  rewriting stored memories.

## Roadmap

| Phase | Deliverable |
| ----- | ----------- |
| 0 | Project skeleton, FastAPI health endpoint |
| 1 | Memory model + persistent SQLite storage |
| 2 | Memory CRUD + import APIs |

| 3 | Memory Explorer UI |
| 4 | Memory health checks (duplicates, contradictions, stale, metadata) |
| 5 | Keyword retrieval baseline |
| 6 | Embedding-based semantic retrieval |
| 7 | Retrieval evaluation benchmark (precision@k, recall@k, MRR) |
| 8 | AI-assisted memory inspector |
| 9 | Consolidated inspector report |
| 10 | End-to-end tests and usability pass |
| 11 | Optional advanced features |
| 12 | Documentation, deployment, submission |
