#!/usr/bin/env python3
"""Check that the frontend and backend are wired together correctly.

Verifies the integration seams that a unit test cannot see, because they span
two processes:

  1. the Vite dev server is up and serving the app shell
  2. the API is reachable and healthy
  3. CORS allows the Vite origin (the preflight a real browser sends first)
  4. CORS refuses an origin that is not on the allow-list
  5. a memory can be written through the API and read back

This does not check that the page *renders* correctly — that needs a browser.

Usage:
    npm run dev                       # terminal 1
    uvicorn app.main:app --port 8000  # terminal 2
    python3 scripts/check_frontend_wiring.py
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_API = "http://127.0.0.1:8000"
DEFAULT_WEB = "http://localhost:5173"


def request(
    url: str, method: str = "GET", headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()
    except urllib.error.URLError as error:
        raise SystemExit(
            f"Cannot reach {url}: {error.reason}\n"
            "Start the servers first, then run this script again."
        ) from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--web", default=DEFAULT_WEB)
    args = parser.parse_args()

    api = args.api.rstrip("/")
    web = args.web.rstrip("/")
    passed = 0
    total = 0

    def check(label: str, ok: bool, detail: str) -> None:
        nonlocal passed, total
        total += 1
        if ok:
            passed += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label} — {detail}")

    print(f"API: {api}\nWeb: {web}\n")

    print("1. Frontend dev server")
    status, _, body = request(web)
    check("serves the app shell", status == 200, f"HTTP {status}")
    check("HTML contains a root element", b'id="root"' in body, "looking for #root")
    check("HTML loads the entry module", b"/src/main.tsx" in body, "looking for /src/main.tsx")

    print("\n2. Backend health")
    status, _, body = request(f"{api}/health")
    check("health endpoint", status == 200, f"HTTP {status}")
    try:
        health = json.loads(body)
        check(
            "reports status ok",
            health.get("status") == "ok",
            f"status={health.get('status')!r}",
        )
    except json.JSONDecodeError:
        check("health returns JSON", False, "response was not JSON")

    print("\n3. CORS: the Vite origin is allowed")
    status, headers, _ = request(
        f"{api}/api/memories", headers={"Origin": web}
    )
    allowed = headers.get("access-control-allow-origin")
    check("simple request is granted", allowed == web, f"ACAO={allowed!r}")

    print("\n4. CORS: a foreign origin is not")
    status, headers, _ = request(
        f"{api}/api/memories", headers={"Origin": "http://evil.example.com"}
    )
    allowed = headers.get("access-control-allow-origin")
    check("foreign origin refused", allowed is None, f"ACAO={allowed!r}")

    print("\n5. CORS: preflight for PATCH is allowed")
    status, headers, _ = request(
        f"{api}/api/memories/some-id",
        method="OPTIONS",
        headers={
            "Origin": web,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    methods = headers.get("access-control-allow-methods", "")
    check("preflight succeeds", status == 200, f"HTTP {status}")
    check("PATCH is permitted", "PATCH" in methods, f"methods={methods!r}")
    check(
        "preflight grants the origin",
        headers.get("access-control-allow-origin") == web,
        f"ACAO={headers.get('access-control-allow-origin')!r}",
    )

    print("\n6. A memory round-trips through the API")
    payload = {
        "content": "Wiring check memory from scripts/check_frontend_wiring.py.",
        "category": "fact",
        "source": "wiring-check",
        "project": "wiring-check",
    }
    req = urllib.request.Request(
        f"{api}/api/memories",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        created = json.loads(response.read())
    check("create returns an id", bool(created.get("id")), f"id={created.get('id')!r}")

    status, _, body = request(f"{api}/api/memories?project=wiring-check")
    rows = json.loads(body)
    check("read back finds it", any(r["id"] == created["id"] for r in rows), f"{len(rows)} row(s)")

    req = urllib.request.Request(
        f"{api}/api/memories/{created['id']}", method="DELETE"
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        check("delete returns 204", response.status == 204, f"HTTP {response.status}")

    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
