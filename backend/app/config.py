"""Runtime configuration.

Values are read from the environment at call time (not import time) so tests can
point the app at a temporary database without reloading modules.
"""

import os
from pathlib import Path

DB_PATH_ENV = "DEVMEMORY_DB_PATH"
CORS_ORIGINS_ENV = "DEVMEMORY_CORS_ORIGINS"

# Vite's dev server defaults. Only these are allowed unless overridden, so a
# deployed frontend must be added explicitly rather than inheriting "*".
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

# backend/app/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent


def get_db_path() -> Path:
    """Location of the SQLite file.

    Defaults to ``backend/devmemory.db``. Override with ``DEVMEMORY_DB_PATH``,
    which is what the test suite uses to get an isolated database per test.
    """
    configured = os.environ.get(DB_PATH_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return BACKEND_DIR / "devmemory.db"


def get_cors_origins() -> list[str]:
    """Origins allowed to call this API from a browser.

    Read as a comma-separated list so deployment can allow a real frontend
    domain without a code change. Never "*": with wildcard origins the browser
    lets any page on the internet read this API's responses.
    """
    raw = os.environ.get(CORS_ORIGINS_ENV, DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
