"""Embedding provider tests.

The local provider is not a language model, so these tests assert what it
actually does — surface and morphology similarity — and assert that it does
*not* do semantics, so nobody can later mistake it for a semantic model.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.services.embeddings import (
    EmbeddingError,
    HostedEmbeddingProvider,
    LocalHashingProvider,
    cosine_similarity,
    get_provider,
)


@pytest.fixture
def provider() -> LocalHashingProvider:
    return LocalHashingProvider(dimensions=1024)


# --- determinism ------------------------------------------------------------


def test_the_same_text_always_produces_the_same_vector(
    provider: LocalHashingProvider,
) -> None:
    first = provider.embed(["The user service uses PostgreSQL."])[0]
    second = provider.embed(["The user service uses PostgreSQL."])[0]

    assert first == second


def test_vectors_survive_a_new_process(provider: LocalHashingProvider) -> None:
    """The hash must not depend on process-local salting.

    Python's built-in hash() for strings is salted per process, which would make
    stored vectors meaningless after a restart. This is asserted indirectly by
    pinning a known vector prefix, and directly by checking a stable hash.
    """
    from app.services.embeddings import _stable_hash

    assert _stable_hash("w:postgresql") == _stable_hash("w:postgresql")
    # A specific value pins the algorithm: if it changes, stored vectors are stale.
    assert _stable_hash("w:postgresql") == 17459730700343955070


def test_vectors_are_unit_length(provider: LocalHashingProvider) -> None:
    vector = provider.embed(["The user service uses PostgreSQL 15."])[0]

    magnitude = sum(value * value for value in vector) ** 0.5
    assert magnitude == pytest.approx(1.0, abs=1e-6)


def test_vector_width_matches_the_declared_dimensions(
    provider: LocalHashingProvider,
) -> None:
    assert len(provider.embed(["anything"])[0]) == provider.dimensions


def test_empty_text_produces_a_zero_vector(provider: LocalHashingProvider) -> None:
    vector = provider.embed([""])[0]

    assert len(vector) == provider.dimensions
    assert all(value == 0.0 for value in vector)


# --- what it can do ---------------------------------------------------------


def test_shared_words_score_high(provider: LocalHashingProvider) -> None:
    left, right = provider.embed(
        [
            "We disabled Redis caching for user records.",
            "Redis caching was disabled for user records.",
        ]
    )

    assert cosine_similarity(left, right) > 0.7


def test_morphology_is_matched(provider: LocalHashingProvider) -> None:
    """The one thing this provider does better than keyword search."""
    left, right = provider.embed(["we disabled caching", "the cache was disabled"])

    assert cosine_similarity(left, right) > 0.4


def test_unrelated_texts_do_not_collide(provider: LocalHashingProvider) -> None:
    """Guards against the hash-width bug: narrow vectors invented similarity."""
    left, right = provider.embed(
        ["kubernetes helm charts", "card numbers must never be logged"]
    )

    assert cosine_similarity(left, right) == 0.0


def test_stopwords_carry_no_signal(provider: LocalHashingProvider) -> None:
    left, right = provider.embed(["the and of to is", "a an but for in"])

    assert cosine_similarity(left, right) == 0.0


# --- what it cannot do ------------------------------------------------------


def test_it_does_not_capture_meaning(provider: LocalHashingProvider) -> None:
    """A paraphrase with no shared words scores zero. This is the limitation."""
    query, memory = provider.embed(
        [
            "Add caching to the user service.",
            "We removed the in-memory account snapshot because balances could go "
            "stale after writes.",
        ]
    )

    assert cosine_similarity(query, memory) < 0.1


def test_it_declares_that_it_does_not_capture_meaning(
    provider: LocalHashingProvider,
) -> None:
    assert provider.captures_meaning is False
    assert "Does not understand meaning" in provider.description


# --- cosine similarity ------------------------------------------------------


def test_identical_vectors_score_one() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_orthogonal_vectors_score_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_opposite_vectors_score_minus_one() -> None:
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_zero_vector_scores_zero_rather_than_dividing_by_zero() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_mismatched_dimensions_score_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_magnitude_does_not_affect_similarity() -> None:
    assert cosine_similarity([1.0, 1.0], [5.0, 5.0]) == pytest.approx(1.0)


# --- provider selection -----------------------------------------------------


def test_auto_falls_back_to_local_without_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVMEMORY_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DEVMEMORY_EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("DEVMEMORY_EMBEDDING_PROVIDER", "auto")

    assert get_provider().name == "local"


def test_auto_uses_hosted_when_a_key_and_model_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVMEMORY_EMBEDDING_PROVIDER", "auto")
    monkeypatch.setenv("DEVMEMORY_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("DEVMEMORY_EMBEDDING_MODEL", "text-embedding-3-small")

    provider = get_provider()

    assert provider.name == "hosted"
    assert provider.captures_meaning is True


def test_explicit_local_ignores_a_configured_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVMEMORY_EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("DEVMEMORY_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("DEVMEMORY_EMBEDDING_MODEL", "text-embedding-3-small")

    assert get_provider().name == "local"


def test_explicit_hosted_without_credentials_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVMEMORY_EMBEDDING_PROVIDER", "hosted")
    monkeypatch.delenv("DEVMEMORY_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DEVMEMORY_EMBEDDING_MODEL", raising=False)

    with pytest.raises(EmbeddingError, match="requires both"):
        get_provider()


# --- hosted provider, against a stub server ---------------------------------
#
# A real key is not available, so the HTTP path is verified against a local
# server that speaks the same protocol. This tests the request shape, the
# response parsing and the error handling; it does not test a real model.


class _StubHandler(BaseHTTPRequestHandler):
    response_status = 200
    response_body: dict = {}
    received: dict = {}

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        _StubHandler.received = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(length)),
        }
        payload = json.dumps(_StubHandler.response_body).encode()
        self.send_response(_StubHandler.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def stub_server():
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def hosted(base_url: str) -> HostedEmbeddingProvider:
    return HostedEmbeddingProvider(
        api_key="test-key",
        model_name="stub-model",
        base_url=base_url,
        timeout=5.0,
        batch_size=2,
    )


def test_hosted_provider_parses_vectors(stub_server: str) -> None:
    _StubHandler.response_status = 200
    _StubHandler.response_body = {
        "data": [
            {"index": 0, "embedding": [0.1, 0.2, 0.3]},
            {"index": 1, "embedding": [0.4, 0.5, 0.6]},
        ]
    }

    vectors = hosted(stub_server).embed(["first", "second"])

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_hosted_provider_sends_the_expected_request(stub_server: str) -> None:
    _StubHandler.response_status = 200
    _StubHandler.response_body = {"data": [{"index": 0, "embedding": [1.0]}]}

    hosted(stub_server).embed(["hello"])

    assert _StubHandler.received["path"] == "/embeddings"
    assert _StubHandler.received["authorization"] == "Bearer test-key"
    assert _StubHandler.received["body"]["model"] == "stub-model"
    assert _StubHandler.received["body"]["input"] == ["hello"]


def test_hosted_provider_orders_by_index_not_response_order(stub_server: str) -> None:
    _StubHandler.response_status = 200
    _StubHandler.response_body = {
        "data": [
            {"index": 1, "embedding": [2.0]},
            {"index": 0, "embedding": [1.0]},
        ]
    }

    assert hosted(stub_server).embed(["a", "b"]) == [[1.0], [2.0]]


def test_hosted_provider_batches_large_inputs(stub_server: str) -> None:
    calls: list[int] = []

    class Counting(_StubHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            calls.append(len(body["input"]))
            payload = json.dumps(
                {
                    "data": [
                        {"index": index, "embedding": [1.0]}
                        for index, _ in enumerate(body["input"])
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Counting)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        provider = hosted(f"http://127.0.0.1:{server.server_address[1]}")
        provider.embed(["a", "b", "c", "d", "e"])
    finally:
        server.shutdown()
        server.server_close()

    assert calls == [2, 2, 1]


def test_hosted_provider_reports_an_http_error_without_leaking_the_key(
    stub_server: str,
) -> None:
    _StubHandler.response_status = 401
    _StubHandler.response_body = {"error": {"message": "invalid api key"}}

    with pytest.raises(EmbeddingError) as caught:
        hosted(stub_server).embed(["hello"])

    message = str(caught.value)
    assert "401" in message
    assert "invalid api key" in message
    assert "test-key" not in message


def test_hosted_provider_rejects_a_short_response(stub_server: str) -> None:
    _StubHandler.response_status = 200
    _StubHandler.response_body = {"data": [{"index": 0, "embedding": [1.0]}]}

    with pytest.raises(EmbeddingError, match="unexpected number of vectors"):
        hosted(stub_server).embed(["a", "b"])


def test_hosted_provider_rejects_an_empty_vector(stub_server: str) -> None:
    _StubHandler.response_status = 200
    _StubHandler.response_body = {"data": [{"index": 0, "embedding": []}]}

    with pytest.raises(EmbeddingError, match="empty vector"):
        hosted(stub_server).embed(["a"])


def test_hosted_provider_reports_an_unreachable_host() -> None:
    provider = hosted("http://127.0.0.1:1")

    with pytest.raises(EmbeddingError, match="Could not reach"):
        provider.embed(["hello"])


def test_hosted_provider_declares_that_it_captures_meaning(stub_server: str) -> None:
    assert hosted(stub_server).captures_meaning is True
    assert "Captures meaning" in hosted(stub_server).description

# --- Gemini provider --------------------------------------------------------
#
# Verified live against gemini-embedding-2 (3072 dimensions); these tests pin the
# request shape and error handling with a stub so they run without a key.


class _GeminiStub(BaseHTTPRequestHandler):
    status = 200
    body: dict = {}
    received: dict = {}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        _GeminiStub.received = {
            "path": self.path,
            "api_key": self.headers.get("x-goog-api-key"),
            "body": json.loads(self.rfile.read(length)),
        }
        payload = json.dumps(_GeminiStub.body).encode()
        self.send_response(_GeminiStub.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def gemini_stub():
    server = HTTPServer(("127.0.0.1", 0), _GeminiStub)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def gemini(base_url: str):
    from app.services.embeddings import GeminiEmbeddingProvider

    return GeminiEmbeddingProvider(
        api_key="google-key", model_name="gemini-embedding-2", base_url=base_url, timeout=5.0
    )


def test_gemini_parses_vectors(gemini_stub: str) -> None:
    _GeminiStub.status = 200
    _GeminiStub.body = {
        "embeddings": [{"values": [0.1, 0.2]}, {"values": [0.3, 0.4]}]
    }

    assert gemini(gemini_stub).embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_gemini_sends_the_expected_request(gemini_stub: str) -> None:
    _GeminiStub.status = 200
    _GeminiStub.body = {"embeddings": [{"values": [1.0]}]}

    gemini(gemini_stub).embed(["hello world"])

    assert _GeminiStub.received["path"].endswith(
        "/models/gemini-embedding-2:batchEmbedContents"
    )
    # The key travels in a header, never in the URL.
    assert _GeminiStub.received["api_key"] == "google-key"
    assert "google-key" not in _GeminiStub.received["path"]
    request = _GeminiStub.received["body"]["requests"][0]
    assert request["model"] == "models/gemini-embedding-2"
    assert request["content"]["parts"][0]["text"] == "hello world"


def test_gemini_reports_errors_without_the_key(gemini_stub: str) -> None:
    _GeminiStub.status = 400
    _GeminiStub.body = {"error": {"message": "API key not valid"}}

    with pytest.raises(EmbeddingError) as caught:
        gemini(gemini_stub).embed(["hello"])

    assert "400" in str(caught.value)
    assert "google-key" not in str(caught.value)


def test_gemini_rejects_a_short_response(gemini_stub: str) -> None:
    _GeminiStub.status = 200
    _GeminiStub.body = {"embeddings": [{"values": [1.0]}]}

    with pytest.raises(EmbeddingError, match="unexpected number of vectors"):
        gemini(gemini_stub).embed(["a", "b"])


def test_gemini_declares_that_it_captures_meaning(gemini_stub: str) -> None:
    provider = gemini(gemini_stub)

    assert provider.name == "gemini"
    assert provider.captures_meaning is True
    assert "Captures meaning" in provider.description


def test_gemini_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVMEMORY_EMBEDDING_PROVIDER", "gemini")
    monkeypatch.delenv("DEVMEMORY_EMBEDDING_API_KEY", raising=False)

    with pytest.raises(EmbeddingError, match="requires"):
        get_provider()


def test_the_relevance_floor_belongs_to_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A floor tuned for hashing is wrong for a trained model, and vice versa."""
    local = LocalHashingProvider(dimensions=64)
    assert local.relevance_floor > 0

    from app.services.embeddings import GeminiEmbeddingProvider

    gemini_provider = GeminiEmbeddingProvider(api_key="k")
    monkeypatch.setenv("DEVMEMORY_SEMANTIC_FLOOR_MEANING", "0")
    assert gemini_provider.relevance_floor == 0.0
    monkeypatch.setenv("DEVMEMORY_SEMANTIC_FLOOR_MEANING", "0.65")
    assert gemini_provider.relevance_floor == 0.65
