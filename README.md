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

Phase 0 complete: project skeleton and a running FastAPI service with a health endpoint.

## Repository layout

```
devmemory/
  backend/            FastAPI service
    app/main.py       API entrypoint
    tests/            pytest suite
    requirements.txt
    .env.example
  .gitignore
  README.md
```

`frontend/`, `data/` and `docs/` are added in later phases, when the feature that needs
them exists.

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

See `backend/.env.example`. Nothing is required in Phase 0. Model provider settings are
introduced in a later phase, and the app must remain usable without them.

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