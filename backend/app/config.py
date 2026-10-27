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
# backend/ -> repository root, where the version-controlled data files live.
REPO_ROOT = BACKEND_DIR.parent


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


# --- health check thresholds ------------------------------------------------
#
# Tuned against the sample dataset: the clearest near-duplicate pair scores
# 0.83, and the next highest non-contradiction pair scores 0.60, so 0.78
# separates them with room to spare. Every threshold is overridable so the
# numbers can be argued with rather than baked in.

def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def near_duplicate_similarity() -> float:
    """Minimum similarity for two memories to be called near-duplicates."""
    return _float_env("DEVMEMORY_HEALTH_NEAR_DUPLICATE_SIMILARITY", 0.78)


def contradiction_context_overlap() -> float:
    """Minimum shared context for two memories to be contradiction candidates.

    Context overlap is used rather than raw similarity: two memories can talk
    about the same subject with completely different words, and still contradict
    each other.
    """
    return _float_env("DEVMEMORY_HEALTH_CONTRADICTION_CONTEXT_OVERLAP", 0.60)


def contradiction_min_shared_tokens() -> int:
    """How many context tokens must be shared before a pair is considered."""
    return _int_env("DEVMEMORY_HEALTH_CONTRADICTION_MIN_SHARED_TOKENS", 2)


def stale_after_days() -> int:
    """Age at which a memory is reported as potentially stale."""
    return _int_env("DEVMEMORY_HEALTH_STALE_AFTER_DAYS", 540)


def very_stale_after_days() -> int:
    """Age at which a memory is reported as severely stale."""
    return _int_env("DEVMEMORY_HEALTH_VERY_STALE_AFTER_DAYS", 900)


def low_confidence_threshold() -> float:
    """Confidence at or below which a decision is considered uncertain."""
    return _float_env("DEVMEMORY_HEALTH_LOW_CONFIDENCE", 0.5)


def vague_content_length() -> int:
    """Content shorter than this is too short to carry useful meaning."""
    return _int_env("DEVMEMORY_HEALTH_VAGUE_CONTENT_LENGTH", 30)


# --- retrieval --------------------------------------------------------------
#
# BM25 defaults. k1 controls how quickly repeated terms stop adding score, and
# b controls how strongly long memories are penalised. These are the values
# from the original BM25 literature and are what a keyword baseline is normally
# measured against, so they stay at the standard unless there is evidence.

def bm25_k1() -> float:
    return _float_env("DEVMEMORY_RETRIEVAL_K1", 1.2)


def bm25_b() -> float:
    return _float_env("DEVMEMORY_RETRIEVAL_B", 0.75)


def default_result_limit() -> int:
    return _int_env("DEVMEMORY_RETRIEVAL_LIMIT", 10)


# --- embeddings -------------------------------------------------------------
#
# Provider selection is explicit rather than guessed: "auto" uses a hosted model
# only when a key and model are configured, and otherwise falls back to the
# local provider. Nothing here makes a network call at import time.

def embedding_provider_name() -> str:
    """Which provider to use: ``auto``, ``local`` or ``hosted``."""
    return os.environ.get("DEVMEMORY_EMBEDDING_PROVIDER", "auto").strip().lower()


def embedding_api_key() -> str:
    return os.environ.get("DEVMEMORY_EMBEDDING_API_KEY", "").strip()


def embedding_model() -> str:
    return os.environ.get("DEVMEMORY_EMBEDDING_MODEL", "").strip()


def embedding_base_url() -> str:
    return os.environ.get(
        "DEVMEMORY_EMBEDDING_BASE_URL", "https://api.openai.com/v1"
    ).strip().rstrip("/")


def local_embedding_dimensions() -> int:
    """Width of the local hashed vector.

    1024 rather than the conventional 256 because measurement showed 256 caused
    hash collisions: unrelated memories landed in the same buckets and scored
    ~0.20 similarity, manufacturing matches that did not exist. At 1024 an
    unrelated pair scores 0.0. A false match is worse than a missed one in a
    tool whose entire value is trustworthiness.
    """
    return _int_env("DEVMEMORY_EMBEDDING_DIMENSIONS", 1024)


def embedding_timeout_seconds() -> float:
    return _float_env("DEVMEMORY_EMBEDDING_TIMEOUT", 20.0)


def embedding_batch_size() -> int:
    """How many texts to send per hosted request."""
    return _int_env("DEVMEMORY_EMBEDDING_BATCH_SIZE", 32)


def semantic_min_similarity() -> float:
    """Below this cosine similarity, a memory is treated as no match at all.

    Hashing can never fully eliminate bucket collisions, so unrelated texts can
    score a few hundredths above zero. Measured: at 1024 dimensions one such
    collision produced 0.024 between a query about Redis and a memory about card
    numbers. Genuine matches in this collection score above 0.3, so a floor
    separates noise from signal. Raising it trades recall for precision, which is
    the right direction for a tool whose findings must be trustworthy.
    """
    return _float_env("DEVMEMORY_SEMANTIC_MIN_SIMILARITY", 0.10)


def benchmark_path() -> Path:
    """Location of the version-controlled benchmark dataset."""
    configured = os.environ.get("DEVMEMORY_BENCHMARK_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return REPO_ROOT / "data" / "benchmark.json"


def benchmark_default_k() -> int:
    """Fallback cut-off when a benchmark query does not specify one."""
    return _int_env("DEVMEMORY_BENCHMARK_K", 5)
