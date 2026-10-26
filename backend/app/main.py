"""DevMemory API entrypoint.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI

SERVICE_NAME = "devmemory-api"
SERVICE_VERSION = "0.1.0"

app = FastAPI(
    title="DevMemory API",
    version=SERVICE_VERSION,
    description=(
        "Memory debugger and quality evaluator for coding agents. "
        "Inspect agent memories, detect quality issues, and measure retrieval quality."
    ),
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness probe used by tests, tooling and deployment checks."""
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}
