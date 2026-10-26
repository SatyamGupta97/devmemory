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

Phase 1 complete: memories are stored in SQLite and survive restarts.

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
  data/
    sample_memories.json
  pytest.ini
  .gitignore
  README.md
```

`frontend/` and `docs/` are added in later phases, when the feature that needs them
exists.

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

## Run the server

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- Health check: <http://127.0.0.1:8000/health>
- Interactive API docs: <http://127.0.0.1:8000/docs>

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

Model provider settings arrive in a later phase. Nothing is required today, and the app
must remain usable without any model access.

## API

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/health` | Liveness check |
| `POST` | `/api/memories` | Add a memory (returns `201`) |
| `GET` | `/api/memories` | List memories, newest first |

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

Memory fields: `content`, `category` (`decision` | `constraint` | `failure` |
`convention` | `fact`), `source`, `project`, optional `confidence` (0–1). The server
assigns `id`, `created_at`, `updated_at`, `status`, and `superseded_by`.

Invalid input returns `422` with the offending field named. Blank or whitespace-only
content is rejected by both Pydantic and a SQLite `CHECK` constraint.

## Sample data

`data/sample_memories.json` holds 14 memories across two projects, seeded with the
problems later phases detect: an exact duplicate, a near-duplicate, a contradictory
database decision, a superseded-vs-current queue decision, missing metadata, and a stale
runtime constraint. A test asserts it always validates against the API schema.

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
