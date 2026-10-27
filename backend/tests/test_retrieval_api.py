"""Retrieval endpoint behaviour."""

from fastapi.testclient import TestClient

MEMORIES = [
    {
        "content": "We disabled Redis caching for user records because stale cache "
                   "entries caused wrong account balances.",
        "category": "failure",
        "source": "incident-142",
        "project": "payments-api",
    },
    {
        "content": "The user service uses PostgreSQL 15 for persistence.",
        "category": "decision",
        "source": "architecture-review",
        "project": "payments-api",
    },
    {
        "content": "The reporting service uses DuckDB for nightly jobs.",
        "category": "decision",
        "source": "analytics-rfc",
        "project": "analytics",
    },
]


def seed(client: TestClient) -> None:
    response = client.post("/api/memories/import", json={"memories": MEMORIES})
    assert response.status_code == 201


def test_retrieve_returns_ranked_matches_with_reasons(client: TestClient) -> None:
    seed(client)

    response = client.post("/api/retrieve", json={"query": "redis caching"})

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "keyword-bm25"
    assert body["returned"] >= 1
    match = body["matches"][0]
    assert match["memory"]["content"].startswith("We disabled Redis caching")
    assert match["score"] > 0
    assert match["matched_terms"][0]["term"] == "caching"
    assert "caching" in match["explanation"]


def test_retrieve_scores_add_up_to_the_terms(client: TestClient) -> None:
    """A user must be able to check the score by hand."""
    seed(client)

    body = client.post("/api/retrieve", json={"query": "user service caching"}).json()

    for match in body["matches"]:
        total = sum(term["contribution"] for term in match["matched_terms"])
        assert abs(match["score"] - total) < 0.01


def test_project_boundary_excludes_other_namespaces(client: TestClient) -> None:
    seed(client)

    body = client.post(
        "/api/retrieve", json={"query": "duckdb", "project": "payments-api"}
    ).json()

    assert body["matches"] == []
    assert body["considered"] == 2
    assert body["project"] == "payments-api"


def test_search_across_all_projects_when_none_is_given(client: TestClient) -> None:
    seed(client)

    body = client.post("/api/retrieve", json={"query": "duckdb"}).json()

    assert len(body["matches"]) == 1
    assert body["matches"][0]["memory"]["project"] == "analytics"


def test_query_with_only_stopwords_is_rejected(client: TestClient) -> None:
    seed(client)

    response = client.post("/api/retrieve", json={"query": "the and is"})

    assert response.status_code == 422
    assert "no searchable terms" in response.json()["detail"]


def test_empty_query_is_rejected(client: TestClient) -> None:
    response = client.post("/api/retrieve", json={"query": "   "})

    assert response.status_code == 422


def test_unknown_project_returns_an_empty_result_not_an_error(
    client: TestClient,
) -> None:
    seed(client)

    response = client.post(
        "/api/retrieve", json={"query": "redis", "project": "no-such-project"}
    )

    assert response.status_code == 200
    assert response.json()["matches"] == []
    assert response.json()["considered"] == 0


def test_a_query_matching_nothing_returns_an_empty_list(client: TestClient) -> None:
    seed(client)

    response = client.post("/api/retrieve", json={"query": "kubernetes helm"})

    assert response.status_code == 200
    assert response.json()["matches"] == []
    assert response.json()["unmatched_query_terms"] == ["kubernetes", "helm"]


def test_limit_is_respected_and_bounded(client: TestClient) -> None:
    seed(client)

    assert client.post(
        "/api/retrieve", json={"query": "user service", "limit": 1}
    ).json()["returned"] == 1
    assert client.post(
        "/api/retrieve", json={"query": "user service", "limit": 0}
    ).status_code == 422
    assert client.post(
        "/api/retrieve", json={"query": "user service", "limit": 51}
    ).status_code == 422


def test_results_are_reproducible_across_calls(client: TestClient) -> None:
    seed(client)

    first = client.post("/api/retrieve", json={"query": "user service"}).json()
    second = client.post("/api/retrieve", json={"query": "user service"}).json()

    assert [m["memory"]["id"] for m in first["matches"]] == [
        m["memory"]["id"] for m in second["matches"]
    ]


def test_retrieval_changes_nothing(client: TestClient) -> None:
    seed(client)

    before = client.get("/api/memories").json()
    client.post("/api/retrieve", json={"query": "user service"})
    after = client.get("/api/memories").json()

    assert before == after


def test_response_states_that_scores_are_not_probabilities(
    client: TestClient,
) -> None:
    seed(client)

    body = client.post("/api/retrieve", json={"query": "redis"}).json()

    assert any("not probabilities" in note for note in body["notes"])


def test_retrieve_is_documented(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "post" in paths["/api/retrieve"]