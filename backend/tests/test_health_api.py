"""Health check endpoint behaviour."""

from fastapi.testclient import TestClient

VALID = {
    "content": "The user service uses PostgreSQL 15 for persistence.",
    "category": "decision",
    "source": "architecture-review",
    "project": "payments-api",
    "confidence": 0.9,
}


def test_health_report_on_an_empty_collection(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["total_memories"] == 0
    assert body["findings"] == []
    assert body["analyzer"] == "deterministic-rules"
    assert body["limitations"]


def test_health_report_lists_findings(client: TestClient) -> None:
    client.post("/api/memories", json=VALID)
    client.post("/api/memories", json=VALID)

    response = client.get("/api/health")

    body = response.json()
    assert body["total_memories"] == 2
    assert body["summary"]["exact_duplicate"] == 1
    finding = body["findings"][0]
    assert finding["issue_type"] == "exact_duplicate"
    assert len(finding["memory_ids"]) == 2
    assert finding["evidence"]
    assert finding["suggested_action"]


def test_health_report_can_be_scoped_to_a_project(client: TestClient) -> None:
    client.post("/api/memories", json=VALID)
    client.post("/api/memories", json={**VALID, "project": "analytics"})

    response = client.get("/api/health", params={"project": "payments-api"})

    assert response.json()["total_memories"] == 1
    assert response.json()["projects"] == ["payments-api"]


def test_running_the_health_check_changes_nothing(client: TestClient) -> None:
    client.post("/api/memories", json=VALID)
    client.post("/api/memories", json={**VALID, "content": "The user service uses MySQL."})

    before = client.get("/api/memories").json()
    client.get("/api/health")
    after = client.get("/api/memories").json()

    assert before == after


def test_health_check_can_be_run_repeatedly_with_the_same_result(
    client: TestClient,
) -> None:
    client.post("/api/memories", json=VALID)
    client.post("/api/memories", json=VALID)

    first = client.get("/api/health").json()
    second = client.get("/api/health").json()

    assert [f["id"] for f in first["findings"]] == [f["id"] for f in second["findings"]]
    assert first["summary"] == second["summary"]


def test_health_endpoint_is_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/health"]


def test_imported_memories_keep_their_original_timestamps(client: TestClient) -> None:
    """Age is the only staleness signal, so imported dates must survive."""
    response = client.post(
        "/api/memories/import",
        json={
            "memories": [
                {**VALID, "created_at": "2020-01-01T00:00:00+00:00"},
            ]
        },
    )

    assert response.status_code == 201
    stored = client.get("/api/memories").json()[0]
    assert stored["created_at"].startswith("2020-01-01")

    report = client.get("/api/health").json()
    assert report["summary"]["potentially_stale"] == 1


def test_memories_without_a_timestamp_are_stamped_by_the_server(
    client: TestClient,
) -> None:
    client.post("/api/memories", json=VALID)

    stored = client.get("/api/memories").json()[0]

    assert stored["created_at"]
    assert stored["created_at"] != stored["updated_at"] or stored["created_at"]
