"""Runtime configuration.

Values are read from the environment at call time (not import time) so tests can
point the app at a temporary database without reloading modules.
"""

import os
from pathlib import Path

DB_PATH_ENV = "DEVMEMORY_DB_PATH"

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
