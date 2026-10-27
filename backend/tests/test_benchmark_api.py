"""Benchmark endpoint tests.

These run against the real sample dataset, because the benchmark file refers to
its contents. A fixture database with invented memories would make every
expectation unresolvable and prove nothing.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample_memories.json"


@pytest.fixture
def seeded(client: TestClient) -> TestClient:
    entries = json.loads(SAMPLE.read_text())
    response = client.post("/api/memories/import", json={"memories": entries})
    assert response.status_code == 201
    return client


def test_the_benchmark_can_be_read(client: TestClient) -> None:
    body = client.get("/api/benchmark").json()

    assert body["version"] >= 1
    assert len(body["queries"]) >= 8
    assert body["queries"][0]["expected"] is not None


def test_keyword_benchmark_runs_and_reports_metrics(seeded: TestClient) -> None:
    response = seeded.post("/api/benchmark/run", json={"strategy": "keyword"})

    assert response.status_code == 200
    body = response.json()
    summary = body["summary"]

    assert body["strategy"] == "keyword-bm25"
    assert summary["valid_queries"] == summary["query_count"]
    assert 0.0 <= summary["mean_precision_at_k"] <= 1.0
    assert 0.0 <= summary["mean_recall_at_k"] <= 1.0
    assert 0.0 <= summary["mrr"] <= 1.0
    assert len(body["cases"]) == summary["query_count"]


def test_every_case_carries_its_own_evidence(seeded: TestClient) -> None:
    body = seeded.post("/api/benchmark/run", json={"strategy": "keyword"}).json()

    for case in body["cases"]:
        assert case["query_id"]
        assert "precision_at_k" in case
        assert "missed" in case
        assert "irrelevant_retrieved" in case


def test_the_benchmark_finds_the_paraphrase_gap(seeded: TestClient) -> None:
    """The known keyword limitation, measured rather than asserted by hand."""
    body = seeded.post("/api/benchmark/run", json={"strategy": "keyword"}).json()

    case = next(item for item in body["cases"] if item["query_id"] == "q05-duplicate-events")
    assert case["recall_at_k"] is not None
    assert case["recall_at_k"] < 1.0


def test_a_query_that_should_match_nothing_is_scored_explicitly(
    seeded: TestClient,
) -> None:
    body = seeded.post("/api/benchmark/run", json={"strategy": "keyword"}).json()

    case = next(item for item in body["cases"] if item["kind"] == "irrelevant")
    assert case["expected_count"] == 0
    assert case["recall_at_k"] is None


def test_semantic_benchmark_runs_after_indexing(seeded: TestClient) -> None:
    seeded.post("/api/embeddings/index", json={})

    response = seeded.post("/api/benchmark/run", json={"strategy": "semantic"})

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "semantic-embedding"
    assert body["summary"]["valid_queries"] == body["summary"]["query_count"]


def test_semantic_benchmark_without_an_index_explains_itself(
    seeded: TestClient,
) -> None:
    response = seeded.post("/api/benchmark/run", json={"strategy": "semantic"})

    assert response.status_code == 409
    assert "POST /api/embeddings/index" in response.json()["detail"]


def test_both_strategies_score_the_same_cases(seeded: TestClient) -> None:
    """A comparison is only meaningful on identical ground truth."""
    seeded.post("/api/embeddings/index", json={})

    keyword = seeded.post("/api/benchmark/run", json={"strategy": "keyword"}).json()
    semantic = seeded.post("/api/benchmark/run", json={"strategy": "semantic"}).json()

    assert [case["query_id"] for case in keyword["cases"]] == [
        case["query_id"] for case in semantic["cases"]
    ]
    assert [case["k"] for case in keyword["cases"]] == [
        case["k"] for case in semantic["cases"]
    ]
    assert [case["expected_count"] for case in keyword["cases"]] == [
        case["expected_count"] for case in semantic["cases"]
    ]


def test_benchmark_results_are_reproducible(seeded: TestClient) -> None:
    first = seeded.post("/api/benchmark/run", json={"strategy": "keyword"}).json()
    second = seeded.post("/api/benchmark/run", json={"strategy": "keyword"}).json()

    assert first["summary"] == second["summary"]


def test_the_benchmark_changes_nothing(seeded: TestClient) -> None:
    before = seeded.get("/api/memories").json()

    seeded.post("/api/benchmark/run", json={"strategy": "keyword"})

    assert seeded.get("/api/memories").json() == before


def test_an_empty_collection_reports_that_nothing_could_be_scored(
    client: TestClient,
) -> None:
    body = client.post("/api/benchmark/run", json={"strategy": "keyword"}).json()

    assert body["summary"]["valid_queries"] == 0
    assert any("Import data/sample_memories.json" in note for note in body["notes"])


def test_a_missing_benchmark_file_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEVMEMORY_BENCHMARK_PATH", str(tmp_path / "absent.json"))

    assert client.get("/api/benchmark").status_code == 404
    assert client.post("/api/benchmark/run", json={}).status_code == 404


def test_an_invalid_cut_off_is_rejected(seeded: TestClient) -> None:
    assert seeded.post("/api/benchmark/run", json={"k": 0}).status_code == 422
    assert seeded.post("/api/benchmark/run", json={"k": 51}).status_code == 422


def test_benchmark_endpoints_are_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/benchmark"]
    assert "post" in paths["/api/benchmark/run"]