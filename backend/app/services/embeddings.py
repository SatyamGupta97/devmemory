"""Embedding providers and vector comparison.

Two implementations behind one interface:

* **local** — deterministic hashed character n-grams. No network, no model, no
  dependency. It captures *surface* similarity: shared words, shared prefixes,
  typos. It does **not** capture meaning, and it says so in its metadata.
* **hosted** — any OpenAI-compatible ``/embeddings`` endpoint. This is the one
  that actually understands paraphrase.

The interface exists so the retrieval code cannot tell them apart, and so the
honest one can be swapped for the strong one by setting two environment
variables. Every result records which provider produced it, because a similarity
score means very different things depending on the answer.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from app.config import (
    embedding_api_key,
    embedding_base_url,
    embedding_batch_size,
    embedding_gemini_model,
    embedding_model,
    embedding_provider_name,
    embedding_timeout_seconds,
    gemini_api_base,
    local_embedding_dimensions,
)
from app.services.text import tokens

#: Weight of a whole-token feature relative to a character n-gram feature.
TOKEN_WEIGHT = 1.0
NGRAM_WEIGHT = 0.4
NGRAM_SIZE = 4

#: Vector width per model, learned from the provider once. Probing on every
#: ``dimensions`` access would spend a network call and money per status request.
_DIMENSION_CACHE: dict[str, int] = {}


class EmbeddingError(RuntimeError):
    """The provider could not produce an embedding.

    Carries a message safe to show a user: no key material, no request bodies.
    """


class EmbeddingProvider(Protocol):
    """Minimal contract the retrieval code depends on."""

    @property
    def name(self) -> str: ...

    @property
    def relevance_floor(self) -> float:
        """Cosine score below which a result is treated as noise.

        A provider property rather than a global constant because the score
        distribution belongs to the model. Hashing produces a near-zero baseline
        and needs a floor to suppress collisions; a trained embedding model has a
        baseline around 0.5, where the same floor would be meaningless and an
        absolute cut-off could not separate relevant from irrelevant anyway.
        """

    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    @property
    def captures_meaning(self) -> bool:
        """False when the provider only compares surface form."""

    @property
    def description(self) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _stable_hash(feature: str) -> int:
    """A hash that is identical across processes and restarts.

    Python's built-in ``hash()`` is salted per process for strings, so using it
    would make stored vectors meaningless after a restart. blake2b is stable.
    """
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _features(text: str) -> dict[str, float]:
    """Token and per-token character n-gram features.

    Tokens catch whole-word overlap. Character n-grams catch the morphology a
    tokeniser misses: "caching" and "cache" share "cach" and "achi".

    The n-grams are built **per token**, not across the whole string. Cross-word
    n-grams ("the u", "e us") are noise: they encode word order and stopwords
    rather than meaning, and measurement showed they manufactured similarity
    between unrelated memories. Stopwords are already excluded by ``tokens``, so
    per-token n-grams never see them either.

    The ``<``/``>`` markers mark word boundaries, so a prefix and a suffix with
    the same letters are distinguished.
    """
    features: dict[str, float] = {}

    for token in tokens(text):
        key = f"w:{token}"
        features[key] = features.get(key, 0.0) + TOKEN_WEIGHT

        padded = f"<{token}>"
        for index in range(len(padded) - NGRAM_SIZE + 1):
            gram = padded[index : index + NGRAM_SIZE]
            feature = f"n:{gram}"
            features[feature] = features.get(feature, 0.0) + NGRAM_WEIGHT

    return features


@dataclass(frozen=True)
class LocalHashingProvider:
    """Deterministic, dependency-free, and honest about being lexical.

    This is a real technique (the hashing trick), not a mock: the vectors are
    genuine and reproducible, and cosine similarity between them is meaningful.
    What it is *not* is a language model, so it cannot connect "caching" to
    "snapshot".
    """

    dimensions: int = 256

    @property
    def name(self) -> str:
        return "local"

    @property
    def model(self) -> str:
        return f"hashed-ngrams-{self.dimensions}"

    @property
    def captures_meaning(self) -> bool:
        return False

    @property
    def relevance_floor(self) -> float:
        """Non-zero: hashing collisions manufacture small similarities."""
        from app.config import semantic_min_similarity

        return semantic_min_similarity()

    @property
    def description(self) -> str:
        return (
            "Deterministic hashed token and character n-gram vectors. Compares "
            "surface form: shared words, shared word stems and typos. Does not "
            "understand meaning, so a paraphrase with no shared words scores zero."
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []

        for text in texts:
            vector = [0.0] * self.dimensions

            for feature, weight in _features(text).items():
                index = _stable_hash(feature) % self.dimensions
                # Sublinear term weighting: a feature repeated ten times is more
                # important than one seen once, but not ten times more.
                vector[index] += weight

            # L2 normalise so cosine similarity is a dot product. A zero vector
            # stays zero and is handled by the comparison function.
            norm = math.sqrt(sum(value * value for value in vector))
            if norm > 0:
                vector = [value / norm for value in vector]

            vectors.append(vector)

        return vectors


@dataclass(frozen=True)
class HostedEmbeddingProvider:
    """Any OpenAI-compatible embeddings endpoint.

    Kept dependency-free (stdlib urllib) so adding semantic search does not add
    a runtime package. The API key is read from the environment at call time and
    never included in an exception message.
    """

    api_key: str
    model_name: str
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 20.0
    batch_size: int = 32
    _dimensions: int = 0

    @property
    def name(self) -> str:
        return "hosted"

    @property
    def model(self) -> str:
        return self.model_name

    @property
    def captures_meaning(self) -> bool:
        return True

    @property
    def relevance_floor(self) -> float:
        """Default 0; configurable, because a floor trades recall for precision."""
        from app.config import semantic_floor_for_meaning

        return semantic_floor_for_meaning()

    @property
    def description(self) -> str:
        return (
            f"Hosted embedding model '{self.model_name}'. Captures meaning, so a "
            "paraphrase with no shared words can still be retrieved. Costs a "
            "network call per query and per indexing run."
        )

    @property
    def dimensions(self) -> int:
        if self._dimensions:
            return self._dimensions
        # Ask the model rather than assuming: dimension differs per model, and a
        # wrong guess would corrupt the stored vectors.
        probe = self.embed(["dimension probe"])
        return len(probe[0])

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start : start + self.batch_size]))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model_name, "input": texts}).encode()
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as error:
            # Read a short reason without echoing the request (which contains the
            # key in a header, and the memories in the body).
            reason = ""
            try:
                detail = json.loads(error.read())
                reason = str(detail.get("error", {}).get("message", ""))[:200]
            except Exception:  # noqa: BLE001 - the body may not be JSON at all
                reason = ""
            raise EmbeddingError(
                f"Embedding provider returned HTTP {error.code}"
                + (f": {reason}" if reason else "")
            ) from error
        except urllib.error.URLError as error:
            raise EmbeddingError(
                f"Could not reach the embedding provider: {error.reason}"
            ) from error
        except json.JSONDecodeError as error:
            raise EmbeddingError("Embedding provider returned invalid JSON") from error

        items = body.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise EmbeddingError(
                "Embedding provider returned an unexpected number of vectors"
            )

        ordered = sorted(items, key=lambda item: item.get("index", 0))
        vectors: list[list[float]] = []
        for item in ordered:
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise EmbeddingError("Embedding provider returned an empty vector")
            vectors.append([float(value) for value in vector])

        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise EmbeddingError("Embedding provider returned inconsistent dimensions")

        return vectors


@dataclass(frozen=True)
class GeminiEmbeddingProvider:
    """Google Gemini embeddings over the native REST API.

    Speaks the same ``EmbeddingProvider`` interface as the others, so retrieval,
    indexing and the benchmark need no knowledge of it. Uses the stdlib rather
    than the ``google-genai`` SDK: one HTTP call does not justify a dependency,
    and the request shape is small enough to read.

    This is the provider that makes "semantic" mean semantic: 3072 dimensions
    trained on meaning, not on character overlap.
    """

    api_key: str
    model_name: str = "gemini-embedding-2"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    timeout: float = 20.0
    batch_size: int = 32
    _dimensions: int = 0

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self.model_name

    @property
    def captures_meaning(self) -> bool:
        return True

    @property
    def relevance_floor(self) -> float:
        """Default 0.

        Measured: unrelated pairs sit near 0.5 while true matches sit near 0.75,
        so no absolute cut-off cleanly separates them. A positive value trades
        recall for precision and is available via
        DEVMEMORY_SEMANTIC_FLOOR_MEANING for anyone who wants it.
        """
        from app.config import semantic_floor_for_meaning

        return semantic_floor_for_meaning()

    @property
    def description(self) -> str:
        return (
            f"Google Gemini embedding model '{self.model_name}'. Captures meaning, "
            "so a paraphrase with no shared words can still be retrieved. Costs a "
            "network call per query and per indexing run."
        )

    @property
    def dimensions(self) -> int:
        if self._dimensions:
            return self._dimensions
        if self.model_name in _DIMENSION_CACHE:
            return _DIMENSION_CACHE[self.model_name]
        probe = self.embed(["dimension probe"])
        _DIMENSION_CACHE[self.model_name] = len(probe[0])
        return len(probe[0])

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start : start + self.batch_size]))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps(
            {
                "requests": [
                    {
                        "model": f"models/{self.model_name}",
                        "content": {"parts": [{"text": text}]},
                    }
                    for text in texts
                ]
            }
        ).encode()

        request = urllib.request.Request(
            f"{self.base_url}/models/{self.model_name}:batchEmbedContents",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                # The key travels in a header, never in the query string, so it
                # cannot leak into a URL that gets logged.
                "x-goog-api-key": self.api_key,
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise EmbeddingError(
                f"Embedding provider returned HTTP {error.code}"
                + self._safe_reason(error)
            ) from error
        except urllib.error.URLError as error:
            raise EmbeddingError(
                f"Could not reach the embedding provider: {error.reason}"
            ) from error
        except json.JSONDecodeError as error:
            raise EmbeddingError("Embedding provider returned invalid JSON") from error

        items = body.get("embeddings")
        if not isinstance(items, list) or len(items) != len(texts):
            raise EmbeddingError(
                "Embedding provider returned an unexpected number of vectors"
            )

        vectors: list[list[float]] = []
        for item in items:
            values = item.get("values") if isinstance(item, dict) else None
            if not isinstance(values, list) or not values:
                raise EmbeddingError("Embedding provider returned an empty vector")
            vectors.append([float(value) for value in values])

        if len({len(vector) for vector in vectors}) != 1:
            raise EmbeddingError("Embedding provider returned inconsistent dimensions")

        return vectors

    @staticmethod
    def _safe_reason(error: urllib.error.HTTPError) -> str:
        try:
            body = json.loads(error.read())
            message = body.get("error", {}).get("message", "")
            if isinstance(message, str) and message:
                return f": {message[:200]}"
        except Exception:  # noqa: BLE001 - the body may not be JSON
            pass
        return ""


def get_provider() -> EmbeddingProvider:
    """Select the provider from configuration.

    ``auto`` prefers a hosted model only when both a key and a model are
    configured. Anything else falls back to the local provider, so the project
    always runs — with a clearly labelled weaker strategy rather than an error.
    """
    configured = embedding_provider_name()
    key = embedding_api_key()
    model = embedding_model()

    if configured == "local":
        return LocalHashingProvider(dimensions=local_embedding_dimensions())

    if configured == "gemini":
        if not key:
            raise EmbeddingError(
                "DEVMEMORY_EMBEDDING_PROVIDER=gemini requires "
                "DEVMEMORY_EMBEDDING_API_KEY (a Google AI Studio key)."
            )
        return GeminiEmbeddingProvider(
            api_key=key,
            model_name=model or embedding_gemini_model(),
            base_url=gemini_api_base(),
            timeout=embedding_timeout_seconds(),
            batch_size=embedding_batch_size(),
        )

    if configured == "hosted":
        if not key or not model:
            raise EmbeddingError(
                "DEVMEMORY_EMBEDDING_PROVIDER=hosted requires both "
                "DEVMEMORY_EMBEDDING_API_KEY and DEVMEMORY_EMBEDDING_MODEL."
            )
        return HostedEmbeddingProvider(
            api_key=key,
            model_name=model,
            base_url=embedding_base_url(),
            timeout=embedding_timeout_seconds(),
            batch_size=embedding_batch_size(),
        )

    if key and model:
        return HostedEmbeddingProvider(
            api_key=key,
            model_name=model,
            base_url=embedding_base_url(),
            timeout=embedding_timeout_seconds(),
            batch_size=embedding_batch_size(),
        )

    return LocalHashingProvider(dimensions=local_embedding_dimensions())


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine similarity in [-1, 1]; 0.0 when either vector is empty.

    Direction, not magnitude: a long memory and a short one can be equally
    similar to a query. Zero vectors (empty or stopword-only text) have no
    direction, so they score 0 rather than dividing by zero.
    """
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))

    if left_norm == 0 or right_norm == 0:
        return 0.0

    return dot / (left_norm * right_norm)