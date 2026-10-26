"""DevMemory API entrypoint.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import memories
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


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness probe used by tests, tooling and deployment checks."""
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}
