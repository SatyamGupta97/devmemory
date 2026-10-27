"""DevMemory API entrypoint.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import benchmark, embeddings, health, memories, report, retrieval
from app.config import get_cors_origins
from app.db import init_db

SERVICE_NAME = "devmemory-api"
SERVICE_VERSION = "0.2.0"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create the database schema before serving traffic.

    ``CREATE TABLE IF NOT EXISTS`` makes this safe on every restart, and the
    database file is what makes memories survive a restart.
    """
    init_db()
    yield


app = FastAPI(
    title="DevMemory API",
    version=SERVICE_VERSION,
    description=(
        "Memory debugger and quality evaluator for coding agents. "
        "Inspect agent memories, detect quality issues, and measure retrieval quality."
    ),
    lifespan=lifespan,
)

app.include_router(memories.router)
app.include_router(health.router)
app.include_router(retrieval.router)
app.include_router(embeddings.router)
app.include_router(benchmark.router)
app.include_router(report.router)

# A browser enforces same-origin policy: a page served from localhost:5173 may
# not read a response from localhost:8000 unless the *server* says so. This
# middleware adds that permission. It is not authentication, and it does not
# protect the API from non-browser clients.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
    # No cookies or auth headers are used, so credentials stay off.
    allow_credentials=False,
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness probe used by tests, tooling and deployment checks."""
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}
