"""Model client tests.

The HTTP path is verified against a local server speaking the same protocol,
because no API key is available here. That covers the request shape, response
parsing, timeouts and error reporting without pretending a real model was used.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.services.llm import LLMClient, LLMError, is_configured, unavailable_reason

MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]


def messages():
    from app.services.llm import ChatMessage

    return [ChatMessage(role=item["role"], content=item["content"]) for item in MESSAGES]


class _Stub(BaseHTTPRequestHandler):
    status = 200
    body: dict = {}
    received: dict = {}

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        _Stub.received = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(length)),
        }
        payload = json.dumps(_Stub.body).encode()
        self.send_response(_Stub.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def stub():
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def client(base_url: str, timeout: float = 5.0) -> LLMClient:
    return LLMClient(
        api_key="test-key", model="stub-model", base_url=base_url, timeout=timeout
    )


def test_parses_the_message_content(stub: str) -> None:
    _Stub.status = 200
    _Stub.body = {
        "model": "stub-model-2026",
        "choices": [{"message": {"role": "assistant", "content": '{"findings": []}'}}],
    }

    completion = client(stub).complete(messages())

    assert completion.text == '{"findings": []}'
    assert completion.model == "stub-model-2026"


def test_sends_the_expected_request(stub: str) -> None:
    _Stub.status = 200
    _Stub.body = {"choices": [{"message": {"content": "{}"}}]}

    client(stub).complete(messages())

    assert _Stub.received["path"] == "/chat/completions"
    assert _Stub.received["authorization"] == "Bearer test-key"
    assert _Stub.received["body"]["model"] == "stub-model"
    # Extraction, not creativity.
    assert _Stub.received["body"]["temperature"] == 0
    assert _Stub.received["body"]["messages"][0]["role"] == "system"


def test_reports_http_errors_without_leaking_the_key(stub: str) -> None:
    _Stub.status = 401
    _Stub.body = {"error": {"message": "invalid api key"}}

    with pytest.raises(LLMError) as caught:
        client(stub).complete(messages())

    text = str(caught.value)
    assert "401" in text
    assert "invalid api key" in text
    assert "test-key" not in text


def test_reports_an_unreachable_provider() -> None:
    with pytest.raises(LLMError, match="Could not reach"):
        client("http://127.0.0.1:1").complete(messages())


def test_rejects_a_response_with_no_choices(stub: str) -> None:
    _Stub.status = 200
    _Stub.body = {"choices": []}

    with pytest.raises(LLMError, match="no choices"):
        client(stub).complete(messages())


def test_rejects_an_empty_message(stub: str) -> None:
    _Stub.status = 200
    _Stub.body = {"choices": [{"message": {"content": "   "}}]}

    with pytest.raises(LLMError, match="empty response"):
        client(stub).complete(messages())


def test_rejects_a_non_json_body(stub: str) -> None:
    _Stub.status = 200
    _Stub.body = {"choices": [{"message": {"content": None}}]}

    with pytest.raises(LLMError):
        client(stub).complete(messages())


# --- configuration ----------------------------------------------------------


def test_not_configured_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVMEMORY_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEVMEMORY_LLM_MODEL", raising=False)

    assert is_configured() is False
    assert "not configured" in unavailable_reason()


def test_the_reason_names_the_missing_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVMEMORY_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("DEVMEMORY_LLM_API_KEY", raising=False)

    assert "DEVMEMORY_LLM_API_KEY is not set" in unavailable_reason()


def test_local_provider_is_reported_as_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no on-device model, so 'local' must not silently do nothing."""
    monkeypatch.setenv("DEVMEMORY_LLM_PROVIDER", "local")
    monkeypatch.delenv("DEVMEMORY_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEVMEMORY_LLM_MODEL", raising=False)

    reason = unavailable_reason()
    assert "not supported" in reason
    assert "DEVMEMORY_LLM_API_KEY" in reason


def test_configured_with_both_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVMEMORY_LLM_API_KEY", "k")
    monkeypatch.setenv("DEVMEMORY_LLM_MODEL", "m")

    assert is_configured() is True
    # No reason to give when there is no problem.
    assert unavailable_reason() == ""

# --- retries ----------------------------------------------------------------


class _Flaky(BaseHTTPRequestHandler):
    statuses: list[int] = [500, 200]
    calls = 0

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        _Flaky.calls += 1
        status = _Flaky.statuses[min(_Flaky.calls - 1, len(_Flaky.statuses) - 1)]
        if status == 200:
            payload = json.dumps(
                {"choices": [{"message": {"content": '{"findings": []}'}}]}
            ).encode()
        else:
            payload = json.dumps({"error": {"message": "overloaded"}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


def flaky_server(statuses: list[int]):
    _Flaky.statuses = statuses
    _Flaky.calls = 0
    server = HTTPServer(("127.0.0.1", 0), _Flaky)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_a_transient_failure_is_retried() -> None:
    """Observed in practice: providers return 503 while shedding load."""
    server, base_url = flaky_server([503, 200])
    try:
        completion = LLMClient(
            api_key="k", model="m", base_url=base_url, timeout=5.0,
            retries=1, retry_backoff_seconds=0,
        ).complete(messages())
    finally:
        server.shutdown()
        server.server_close()

    assert completion.text == '{"findings": []}'
    assert _Flaky.calls == 2


def test_retries_are_bounded() -> None:
    server, base_url = flaky_server([500, 500, 500])
    try:
        with pytest.raises(LLMError, match="HTTP 500"):
            LLMClient(
                api_key="k", model="m", base_url=base_url, timeout=5.0,
                retries=1, retry_backoff_seconds=0,
            ).complete(messages())
    finally:
        server.shutdown()
        server.server_close()

    # One attempt plus one retry, then it gives up.
    assert _Flaky.calls == 2


def test_a_client_error_is_not_retried() -> None:
    """A 401 or 400 will fail the same way next time; retrying wastes time."""
    server, base_url = flaky_server([401, 200])
    try:
        with pytest.raises(LLMError, match="HTTP 401"):
            LLMClient(
                api_key="k", model="m", base_url=base_url, timeout=5.0,
                retries=3, retry_backoff_seconds=0,
            ).complete(messages())
    finally:
        server.shutdown()
        server.server_close()

    assert _Flaky.calls == 1


def test_no_retries_when_disabled() -> None:
    server, base_url = flaky_server([503, 200])
    try:
        with pytest.raises(LLMError, match="HTTP 503"):
            LLMClient(
                api_key="k", model="m", base_url=base_url, timeout=5.0,
                retries=0, retry_backoff_seconds=0,
            ).complete(messages())
    finally:
        server.shutdown()
        server.server_close()

    assert _Flaky.calls == 1
