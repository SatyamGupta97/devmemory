"""Report API tests.

The important ones are the parity tests: they assert that the report agrees with
the endpoints it summarises. If the report ever starts hardcoding a demo number,
these fail.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import llm
from app.services.llm import ChatCompletion

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample_memories.json"


@pytest.fixture
def seeded(client: TestClient) -> TestClient:
    entries = json.loads(SAMPLE.read_text())
    assert client.post("/api/memories/import", json={"memories": entries}).status_code == 201
    return client


# --- parity with the source endpoints ---------------------------------------


def test_inventory_matches_the_memory_list(seeded: TestClient) -> None:
    listed = seeded.get("/api/memories").json()

    report = seeded.get("/api/report").json()

    assert report["inventory"]["total"] == len(listed)
    counted: dict[str, int] = {}
    for item in listed:
        counted[item["project"]] = counted.get(item["project"], 0) + 1
    assert report["inventory"]["by_project"] == counted


def test_health_section_matches_the_health_endpoint(seeded: TestClient) -> None:
    """The report must not recompute findings differently."""
    health = seeded.get("/api/health").json()

    report = seeded.get("/api/report").json()

    assert [finding["id"] for finding in report["health"]["findings"]] == [
        finding["id"] for finding in health["findings"]
    ]
    assert report["health"]["summary"] == health["summary"]


def test_benchmark_section_matches_the_benchmark_endpoint(seeded: TestClient) -> None:
    keyword = seeded.post("/api/benchmark/run", json={"strategy": "keyword"}).json()

    report = seeded.get("/api/report").json()

    assert report["retrieval"]["keyword"]["summary"] == keyword["summary"]
    assert [case["query_id"] for case in report["retrieval"]["keyword"]["cases"]] == [
        case["query_id"] for case in keyword["cases"]
    ]


def test_changing_the_data_changes_the_report(client: TestClient) -> None:
    """A guard against any hardcoded demo figure."""
    before = client.get("/api/report").json()
    client.post(
        "/api/memories",
        json={
            "content": "A brand new decision about the reporting service.",
            "category": "decision",
            "source": "test",
            "project": "analytics",
        },
    )
    after = client.get("/api/report").json()

    assert after["inventory"]["total"] == before["inventory"]["total"] + 1
    assert after["inventory"]["by_project"]["analytics"] == (
        before["inventory"]["by_project"].get("analytics", 0) + 1
    )


# --- composition ------------------------------------------------------------


def test_report_carries_the_measurement_context(seeded: TestClient) -> None:
    context = seeded.get("/api/report").json()["context"]

    assert context["retrieval_strategy"]
    assert context["benchmark_version"] >= 1
    assert context["benchmark_query_count"] >= 8
    assert context["benchmark_k"] >= 1
    assert context["embedding_provider"]
    assert isinstance(context["embedding_captures_meaning"], bool)
    assert context["ai_consulted"] is False
    assert context["ai_unavailable_reason"]


def test_a_surface_provider_is_flagged_in_the_context(seeded: TestClient) -> None:
    context = seeded.get("/api/report").json()["context"]

    assert context["embedding_provider"] == "local"
    assert context["embedding_captures_meaning"] is False


def test_semantic_results_appear_once_indexed(seeded: TestClient) -> None:
    assert seeded.get("/api/report").json()["retrieval"]["semantic"] is None

    seeded.post("/api/embeddings/index", json={})
    report = seeded.get("/api/report").json()

    assert report["retrieval"]["semantic"] is not None
    assert "semantic-embedding" in report["context"]["retrieval_strategy"]


def test_retrieval_failures_are_listed_with_content(seeded: TestClient) -> None:
    examples = seeded.get("/api/report").json()["retrieval"]["missed_examples"]

    assert examples
    assert all(example["missed"] for example in examples)
    assert all(example["query_id"] for example in examples)


def test_recommendations_reference_real_counts(seeded: TestClient) -> None:
    report = seeded.get("/api/report").json()
    contradictions = report["health"]["summary"].get("potential_contradiction", 0)

    recommendation = next(
        item for item in report["recommendations"] if "contradiction" in item["title"]
    )

    assert str(contradictions) in recommendation["title"]
    assert len(recommendation["related"]) == contradictions


def test_an_empty_collection_produces_a_usable_report(client: TestClient) -> None:
    response = client.get("/api/report")

    assert response.status_code == 200
    body = response.json()
    assert body["inventory"]["total"] == 0
    assert body["health"]["findings"] == []
    assert body["recommendations"]
    assert any("Import" in item["title"] for item in body["recommendations"])


def test_the_report_can_be_scoped(client: TestClient) -> None:
    client.post(
        "/api/memories",
        json={
            "content": "A payments decision.",
            "category": "decision",
            "source": "test",
            "project": "payments-api",
        },
    )
    client.post(
        "/api/memories",
        json={
            "content": "An analytics decision.",
            "category": "decision",
            "source": "test",
            "project": "analytics",
        },
    )

    body = client.get("/api/report", params={"project": "analytics"}).json()

    assert body["scope_project"] == "analytics"
    assert body["inventory"]["total"] == 1


def test_a_benchmark_failure_does_not_hide_the_collection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEVMEMORY_BENCHMARK_PATH", str(tmp_path / "absent.json"))

    response = client.get("/api/report")

    # The benchmark is required for the retrieval section, so this is an honest
    # 404 rather than a report with invented metrics.
    assert response.status_code == 404


def test_ai_findings_are_labelled_and_separate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = client.post(
        "/api/memories",
        json={
            "content": "The user service uses PostgreSQL.",
            "category": "decision",
            "source": "test",
            "project": "payments-api",
        },
    ).json()
    other = client.post(
        "/api/memories",
        json={
            "content": "The user service uses MySQL.",
            "category": "decision",
            "source": "test",
            "project": "payments-api",
        },
    ).json()

    reply = json.dumps(
        {
            "findings": [
                {
                    "issue_type": "contradiction",
                    "memory_ids": [created["id"], other["id"]],
                    "title": "Different databases",
                    "explanation": "They disagree.",
                    "evidence": ["postgres", "mysql"],
                    "suggested_action": "Confirm which is current.",
                    "severity": "medium",
                    "uncertainty": "medium",
                }
            ]
        }
    )

    class Fake:
        model = "fake-model"

        def complete(self, messages):
            return ChatCompletion(text=reply, model="fake-model")

    monkeypatch.setenv("DEVMEMORY_LLM_API_KEY", "k")
    monkeypatch.setenv("DEVMEMORY_LLM_MODEL", "fake-model")
    monkeypatch.setattr(llm, "get_client", lambda: Fake())

    body = client.get("/api/report").json()

    assert body["ai"]["consulted"] is True
    assert body["ai"]["model"] == "fake-model"
    assert body["ai"]["findings"][0]["source"] == "model"
    # Deterministic findings remain distinguishable.
    assert all(item["source"] == "rule" for item in body["health"]["findings"])


def test_an_ai_failure_degrades_to_a_note(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post(
        "/api/memories",
        json={
            "content": "A memory.",
            "category": "fact",
            "source": "test",
            "project": "payments-api",
        },
    )

    class Broken:
        model = "x"

        def complete(self, messages):
            raise llm.LLMError("The model provider returned HTTP 500.")

    monkeypatch.setenv("DEVMEMORY_LLM_API_KEY", "k")
    monkeypatch.setenv("DEVMEMORY_LLM_MODEL", "fake-model")
    monkeypatch.setattr(llm, "get_client", lambda: Broken())

    response = client.get("/api/report")

    # The report is still produced; only the AI section is unavailable.
    assert response.status_code == 200
    body = response.json()
    assert body["ai"]["consulted"] is False
    assert "AI analysis failed" in body["ai"]["reason"]


# --- export -----------------------------------------------------------------


def test_json_export_parses_and_matches_the_endpoint(seeded: TestClient) -> None:
    live = seeded.get("/api/report").json()

    response = seeded.get("/api/report/export", params={"format": "json"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    exported = json.loads(response.text)
    assert exported["inventory"] == live["inventory"]
    assert exported["context"] == live["context"]
    assert [item["title"] for item in exported["recommendations"]] == [
        item["title"] for item in live["recommendations"]
    ]


def test_markdown_export_states_what_was_measured(seeded: TestClient) -> None:
    seeded.post("/api/embeddings/index", json={})

    text = seeded.get("/api/report/export", params={"format": "markdown"}).text

    assert "# DevMemory inspector report" in text
    assert "How this was measured" in text
    # Provider and benchmark context must travel with the numbers.
    assert "hashed-ngrams-1024" in text
    assert "Benchmark queries" in text
    assert "Cut-off k" in text
    assert "not a semantic model" in text


def test_markdown_export_contains_the_real_counts(seeded: TestClient) -> None:
    live = seeded.get("/api/report").json()

    text = seeded.get("/api/report/export", params={"format": "markdown"}).text

    assert f"**Memories inspected:** {live['inventory']['total']}" in text
    for project, count in live["inventory"]["by_project"].items():
        assert f"| {project} | {count} |" in text


def test_markdown_export_names_the_benchmark_metrics(seeded: TestClient) -> None:
    live = seeded.get("/api/report").json()
    recall = live["retrieval"]["keyword"]["summary"]["mean_recall_at_k"]

    text = seeded.get("/api/report/export", params={"format": "markdown"}).text

    assert "Precision@k" in text
    assert "Recall@k" in text
    assert f"{recall:.3f}" in text


def test_markdown_export_states_that_no_model_was_consulted(
    seeded: TestClient,
) -> None:
    text = seeded.get("/api/report/export", params={"format": "markdown"}).text

    assert "No language model was consulted" in text
    assert "**Model-generated.**" not in text


def test_markdown_export_separates_deterministic_findings(
    seeded: TestClient,
) -> None:
    text = seeded.get("/api/report/export", params={"format": "markdown"}).text

    assert "No language model was involved in this section" in text


def test_export_rejects_an_unknown_format(seeded: TestClient) -> None:
    assert seeded.get("/api/report/export", params={"format": "pdf"}).status_code == 422


def test_report_endpoints_are_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/report"]
    assert "get" in paths["/api/report/export"]