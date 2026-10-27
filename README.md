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

Phase 5 complete: a keyword retrieval baseline ranks memories against a coding task and
explains every point of every score. A deterministic health check inspects the
collection for duplicates, contradictions, stale entries and weak metadata. A React UI
covers the full memory lifecycle, the health check, and a retrieval playground.

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
        health.py       deterministic health analysis
        retrieval.py    BM25 keyword ranking
        text.py         normalisation and similarity
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
    smoke_api.py              end-to-end API checks
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
python3 scripts/smoke_api.py

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

Backend tests also run from the repository root (`backend/.venv/bin/pytest -v`). The
shared configuration lives in `pytest.ini`, which puts `backend/` on `sys.path` so test
modules can import the service as `from app.main import app`.

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
| `GET` | `/api/health` | Run the health check and return the findings |
| `POST` | `/api/retrieve` | Rank memories for a coding task, with reasons |

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

`data/sample_memories.json` holds 19 memories across three namespaces, seeded with every
problem the tool detects: an exact duplicate, a near-duplicate, three contradictions
(database choice, queue technology, Python version), deliberately old entries, weak
sources, a placeholder namespace, vague content, and one memory containing
instruction-like text.

It also holds one memory that is semantically relevant to caching but shares no word with
the usual caching query — so the keyword baseline's blind spot is demonstrable rather than
theoretical, and Phase 6 has something to beat. A test asserts the file always validates
against the API schema.

## Memory health check

`GET /api/health` analyses the stored memories and returns findings. It is
**read-only**: it never modifies, deletes or rewrites a memory. Every finding is a
suggestion for a human to act on.

```bash
curl http://127.0.0.1:8000/api/health
```

Add `?project=payments-api` to scope the analysis to one namespace.

### What it detects

| Issue type | Severity | What it means |
| ---------- | -------- | ------------- |
| `exact_duplicate` | medium | Two memories are identical once case and punctuation are ignored |
| `near_duplicate` | low | The same statement in different words; they do not contradict each other |
| `potential_contradiction` | medium | The same subject, different values — they cannot all be current |
| `potentially_stale` | low–high | Old enough that it may no longer reflect the project |
| `superseded_memory` | info | A retired decision, kept on purpose so history stays visible |
| `missing_confidence` | low | A decision or constraint with no confidence recorded |
| `low_confidence` | medium | A decision the memory itself flags as doubtful |
| `unreliable_source` | medium | A source nobody can go and check |
| `placeholder_project` | medium | Filed under a namespace like `unknown` |
| `vague_content` | low | Too short to carry useful meaning |
| `suspicious_content` | high | Reads like a command rather than a record of project knowledge |

### Why some things are deliberately not flagged

- **Duplicates are only detected within a project.** The same convention stated in two
  projects is legitimate, not a duplicate.
- **Contradictions need a shared subject.** Two memories are only compared when they
  share context tokens, so "the user service uses PostgreSQL" and "the reporting
  service uses DuckDB" are not treated as a conflict.
- **A year difference is not a contradiction.** "Migrated in 2025" versus "migrated in
  2024" states *when*, not *what*.
- **A contradiction is a candidate, not a verdict.** Two memories can disagree and both
  be right — different services, different environments, different points in time. Each
  contradiction finding says this in its `uncertainty` field.
- **Staleness is age only.** The schema records no review date, so every stale finding
  says that age is the only available signal.

### How the rules work

Duplicate and near-duplicate detection use a normalised text comparison plus a token
overlap score, with the stronger of the two winning. Contradiction detection is
different: it looks for two memories that share a *subject* but name different
*values* — so it catches a contradiction even when the two sentences share no
particular words.

The thresholds are configuration, not magic numbers, and were tuned against the sample
dataset: the clearest near-duplicate pair scores `0.83` and the next highest
non-contradiction pair scores `0.60`, so `0.78` separates them. Override any of them:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DEVMEMORY_HEALTH_NEAR_DUPLICATE_SIMILARITY` | `0.78` | Minimum similarity for a near-duplicate |
| `DEVMEMORY_HEALTH_CONTRADICTION_CONTEXT_OVERLAP` | `0.60` | Minimum shared subject for a contradiction |
| `DEVMEMORY_HEALTH_CONTRADICTION_MIN_SHARED_TOKENS` | `2` | How many shared words are needed |
| `DEVMEMORY_HEALTH_STALE_AFTER_DAYS` | `540` | Age at which a memory is reported stale |
| `DEVMEMORY_HEALTH_VERY_STALE_AFTER_DAYS` | `900` | Age at which it is reported severely stale |
| `DEVMEMORY_HEALTH_LOW_CONFIDENCE` | `0.5` | Confidence at or below which a decision is doubtful |
| `DEVMEMORY_HEALTH_VAGUE_CONTENT_LENGTH` | `30` | Content shorter than this is too vague |

Retrieval:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DEVMEMORY_RETRIEVAL_K1` | `1.2` | BM25 term-saturation parameter |
| `DEVMEMORY_RETRIEVAL_B` | `0.75` | BM25 length-normalisation parameter |
| `DEVMEMORY_RETRIEVAL_LIMIT` | `10` | Default number of results |

### Memory timestamps

`POST /api/memories` and the import endpoint accept an optional `created_at`. Real
memory systems hold memories captured weeks or months ago, and without the original
date "stale" could never be detected. When it is omitted the server stamps the current
time.

```json
{
  "content": "Background jobs are queued through Celery with Redis as the broker.",
  "category": "decision",
  "source": "old-wiki-page",
  "project": "analytics",
  "confidence": 0.3,
  "created_at": "2023-05-19T09:00:00+00:00"
}
```

## Retrieval

`POST /api/retrieve` ranks memories against a coding task and explains the result.

```bash
curl -X POST http://127.0.0.1:8000/api/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query": "Add caching to the user service.", "project": "payments-api", "limit": 5}'
```

The response carries, for every match:

| Field | Meaning |
| ----- | ------- |
| `score` | BM25 relevance. Comparable within one query only |
| `matched_terms` | Every query term that hit, with its `idf`, `term_frequency` and `contribution` |
| `explanation` | A sentence naming the terms and the largest contributor |
| `memory` | The full memory, including `status` and `superseded_by` |

At the top level, `unmatched_query_terms` names the query terms that found nothing —
which is how the tool explains a *miss* rather than quietly returning a short list.

**The score is the sum of its term contributions.** That is a tested invariant, so a
reader can check the arithmetic by hand instead of trusting a number.

### Why BM25, and why these parameters

BM25 is the standard relevance baseline: anything cleverer has to beat it to earn its
place. `k1 = 1.2` and `b = 0.75` are the literature defaults, kept unchanged so the
baseline is an honest comparison rather than one tuned to flatter the demo. Both are
overridable via `DEVMEMORY_RETRIEVAL_K1` and `DEVMEMORY_RETRIEVAL_B`.

### The failure this baseline has, on purpose

For the query `"Add caching to the user service."`, the actual result is:

| Rank | Memory | Score |
| ---- | ------ | ----- |
| 1 | The user service uses MySQL for persistence. | 2.173 |
| 2 | The user service uses PostgreSQL 15 for persistence. | 2.035 |
| 3 | The user service uses PostgreSQL 15 for persistence. | 2.035 |
| 4 | **We disabled Redis caching for user records…** | **1.880** |

The memory that is actually relevant to caching ranks **fourth**, behind two database
decisions that have nothing to do with the task. And this memory:

> We removed the in-memory account snapshot because balances could go stale after writes.

scores **zero** and is never returned at all, because it shares no word with the query.

Both are real limitations of keyword search, and both are left in place deliberately:

- **Common words outrank specific ones.** "user" and "service" appear in many memories,
  so the memories that repeat them score well regardless of whether they answer the task.
  BM25's length normalisation also favours short memories.
- **Meaning without shared words is invisible.** "caching" and "snapshot" describe the
  same concern; a keyword index cannot know that.

Fixing these is the job of semantic retrieval, and *proving* the fix is the job of the
benchmark. Tuning BM25 until the demo looked right would have destroyed both.

### Other deliberate choices

- **Superseded memories are returned, and labelled.** Hiding a retired decision would
  hide exactly the failure this tool exists to expose.
- **Queries made only of stopwords are rejected** with `422`, not answered with an
  arbitrary list.
- **An unknown project returns an empty result**, not an error: an empty namespace is a
  valid answer.
- **Nothing is written.** Retrieval is a read, and a test asserts the collection is
  unchanged afterwards.

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

