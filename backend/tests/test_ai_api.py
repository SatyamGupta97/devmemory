"""AI analysis endpoint behaviour."""

import json

import pytest
from fastapi.testclient import TestClient

from app.services import llm
from app.services.llm import ChatCompletion, LLMError

MEMORY = {
    "content": "We disabled Redis caching for user records.",
    "category": "failure",
    "source": "incident-142",
    "project": "payments-api",
}


class FakeClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.model = "fake-model"
        self.messages = None

    def complete(self, messages):
        self.messages = messages
        return ChatCompletion(text=self.reply, model=self.model)


def reply_for(memory_ids: list[str]) -> str:
    return json.dumps(
        {
            "findings": [
                {
                    "issue_type": "contradiction",
                    "memory_ids": memory_ids,
                    "title": "Two memories disagree",
                    "explanation": "They name different databases.",
                    "evidence": ["uses PostgreSQL", "uses MySQL"],
                    "suggested_action": "Confirm which is current and supersede the other.",
                    "severity": "medium",
                    "uncertainty": "high",
                }
            ]
        }
    )


def test_status_reports_unavailable_without_configuration(
    client: TestClient,
) -> None:
    body = client.get("/api/health/ai/status").json()

    assert body["available"] is False
    assert body["provider"] == "none"
    assert "DEVMEMORY_LLM_API_KEY" in body["reason"]


def test_status_reports_available_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEVMEMORY_LLM_API_KEY", "test-key")
    monkeypatch.setenv("DEVMEMORY_LLM_MODEL", "test-model")

    body = client.get("/api/health/ai/status").json()

    assert body["available"] is True
    assert body["model"] == "test-model"
    assert body["reason"] is None


def test_analysis_without_configuration_returns_409(client: TestClient) -> None:
    client.post("/api/memories", json=MEMORY)

    response = client.post("/api/health/ai", json={})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "DEVMEMORY_LLM_API_KEY" in detail
    # The deterministic check is still available.
    assert client.get("/api/health").status_code == 200


def test_the_deterministic_report_still_works_without_a_model(
    client: TestClient,
) -> None:
    client.post("/api/memories", json=MEMORY)

    body = client.get("/api/health").json()

    assert body["analyzer"] == "deterministic-rules"
    assert all(finding["source"] == "rule" for finding in body["findings"])


def test_analysis_returns_validated_findings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = client.post("/api/memories", json=MEMORY).json()
    other = client.post(
        "/api/memories",
        json={**MEMORY, "content": "The user service uses MySQL.", "category": "decision"},
    ).json()
    monkeypatch.setattr(
        llm, "get_client", lambda: FakeClient(reply_for([created["id"], other["id"]]))
    )

    response = client.post("/api/health/ai", json={})

    assert response.status_code == 200
    body = response.json()
    assert len(body["findings"]) == 1
    finding = body["findings"][0]
    assert finding["source"] == "model"
    assert finding["issue_type"] == "contradiction"
    assert finding["uncertainty"] == "high"
    assert finding["evidence"]
    assert body["analyzed_memories"] == 2


def test_findings_naming_unknown_ids_are_rejected_and_reported(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/api/memories", json=MEMORY)
    monkeypatch.setattr(
        llm, "get_client", lambda: FakeClient(reply_for(["invented-id"]))
    )

    body = client.post("/api/health/ai", json={}).json()

    assert body["findings"] == []
    assert any("invented-id" in item for item in body["rejected"])


def test_a_model_failure_is_reported_as_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/api/memories", json=MEMORY)

    class Broken:
        model = "x"

        def complete(self, messages):
            raise LLMError("The model provider returned HTTP 500.")

    monkeypatch.setattr(llm, "get_client", lambda: Broken())

    response = client.post("/api/health/ai", json={})

    assert response.status_code == 502
    assert "HTTP 500" in response.json()["detail"]


def test_an_empty_collection_with_a_model_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm, "get_client", lambda: FakeClient('{"findings": []}'))

    response = client.post("/api/health/ai", json={})

    assert response.status_code == 422
    assert "no memories" in response.json()["detail"]


def test_analysis_writes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = client.post("/api/memories", json=MEMORY).json()
    monkeypatch.setattr(
        llm, "get_client", lambda: FakeClient(reply_for([created["id"]]))
    )
    before = client.get("/api/memories").json()

    client.post("/api/health/ai", json={})

    assert client.get("/api/memories").json() == before


def test_the_api_key_never_appears_in_a_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-super-secret-value-1234567890"
    monkeypatch.setenv("DEVMEMORY_LLM_API_KEY", secret)
    monkeypatch.setenv("DEVMEMORY_LLM_MODEL", "test-model")
    monkeypatch.setattr(
        llm, "get_client", lambda: FakeClient(reply_for(["nope"]))
    )
    client.post("/api/memories", json=MEMORY)

    raw = client.post("/api/health/ai", json={}).text

    assert secret not in raw


def test_the_project_filter_limits_what_is_analysed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/api/memories", json=MEMORY)
    client.post("/api/memories", json={**MEMORY, "project": "analytics"})
    captured: dict = {}

    class Recorder(FakeClient):
        def complete(self, messages):
            captured["prompt"] = "\n".join(item.content for item in messages)
            return super().complete(messages)

    monkeypatch.setattr(llm, "get_client", lambda: Recorder('{"findings": []}'))

    body = client.post("/api/health/ai", json={"project": "analytics"}).json()

    assert body["analyzed_memories"] == 1
    assert "payments-api" not in captured["prompt"]


def test_ai_endpoints_are_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "post" in paths["/api/health/ai"]
    assert "get" in paths["/api/health/ai/status"]
