"""CORS behaviour.

Without this, the browser blocks the frontend from reading API responses even
though the request itself succeeds. The failure appears in the browser console,
not in the server log, which makes it confusing to debug.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import get_cors_origins

ALLOWED_ORIGIN = "http://localhost:5173"
DISALLOWED_ORIGIN = "http://evil.example.com"


def test_configured_frontend_origin_may_read_responses(client: TestClient) -> None:
    response = client.get("/api/memories", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_unknown_origin_is_not_granted_access(client: TestClient) -> None:
    response = client.get("/api/memories", headers={"Origin": DISALLOWED_ORIGIN})

    # The request still runs, but without the header the browser refuses to hand
    # the body to page JavaScript.
    assert "access-control-allow-origin" not in response.headers


def test_preflight_for_patch_is_allowed(client: TestClient) -> None:
    """A PATCH with a JSON body triggers a preflight OPTIONS request first."""
    response = client.options(
        "/api/memories/some-id",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_delete_preflight_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/api/memories/some-id",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "DELETE"},
    )

    assert "DELETE" in response.headers["access-control-allow-methods"]


def test_origins_are_read_as_a_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DEVMEMORY_CORS_ORIGINS", " https://app.example.com , https://staging.example.com ,"
    )

    assert get_cors_origins() == [
        "https://app.example.com",
        "https://staging.example.com",
    ]


def test_defaults_never_include_a_wildcard() -> None:
    """A wildcard would let any page on the internet read this API."""
    assert "*" not in get_cors_origins()
