#!/usr/bin/env python3
"""End-to-end smoke test for the Phase 2 memory APIs.

Runs against a live server using only the standard library, so there is nothing
to install. Every step prints what it expected and what it got.

Usage:
    # in one terminal
    uvicorn app.main:app --port 8000

    # in another
    python3 scripts/smoke_phase2.py
    python3 scripts/smoke_phase2.py --base-url http://127.0.0.1:8013

Each run uses its own project namespace (demo-<random>), so it is safe to run
repeatedly and it never touches your real memories.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from uuid import uuid4

MEMORIES = [
    {
        "content": "The user service uses PostgreSQL 15 for persistence.",
        "category": "decision",
        "source": "architecture-review",
        "project": "{project}",
        "confidence": 0.9,
    },
    {
        "content": "The user service uses PostgreSQL 15 for persistence.",
        "category": "decision",
        "source": "onboarding-notes",
        "project": "{project}",
        "confidence": 0.9,
    },
    {
        "content": "We disabled Redis caching for user records because stale entries caused wrong balances.",
        "category": "failure",
        "source": "incident-142",
        "project": "{project}",
        "confidence": 0.95,
    },
    {
        "content": "Background jobs are queued through Celery with Redis as the broker.",
        "category": "decision",
        "source": "old-wiki-page",
        "project": "{project}",
        "confidence": 0.3,
    },
    {
        "content": "We migrated from Celery to Dramatiq for background jobs in 2025.",
        "category": "decision",
        "source": "eng-blog-draft",
        "project": "{project}",
        "confidence": 0.75,
    },
    {
        "content": "Never log full card numbers or CVV values; use the last four digits only.",
        "category": "constraint",
        "source": "security-guideline",
        "project": "{project}",
        "confidence": 1.0,
    },
]


def call(
    base_url: str, method: str, path: str, body: object | None = None
) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, (json.loads(raw) if raw else None)


class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, label: str, expected: object, actual: object, ok: bool) -> None:
        mark = "PASS" if ok else "FAIL"
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        print(f"  [{mark}] {label}: expected {expected}, got {actual}")

    def summary(self) -> int:
        total = self.passed + self.failed
        print(f"\n{self.passed}/{total} checks passed")
        return 0 if self.failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    # A uuid, not a timestamp: two runs started within the same second would
    # otherwise share a namespace, and the second run's rows would inflate the
    # first run's counts.
    project = f"demo-{uuid4().hex[:12]}"
    results = Results()

    print(f"Target: {base}")
    print(f"Namespace: {project}\n")

    status, health = None, None
    try:
        status, health = call(base, "GET", "/health")
    except urllib.error.URLError as error:
        print(f"Cannot reach the API at {base}: {error.reason}")
        print("Start it with: uvicorn app.main:app --port 8000")
        return 2

    if status != 200:
        print(f"GET /health returned {status}; the API is not healthy.")
        return 2

    memories = [{**m, "project": project} for m in MEMORIES]

    print("1. Bulk import")
    # Guard: if the namespace were ever reused, later counts would be inflated
    # and the failures would look mysterious. Catch it here instead.
    status, existing = call(base, "GET", f"/api/memories?project={project}")
    if status != 200 or existing:
        print(f"Namespace '{project}' is not empty; refusing to continue.")
        return 2

    status, body = call(base, "POST", "/api/memories/import", {"memories": memories})
    results.check("POST /api/memories/import", 201, status, status == 201)
    imported = body["ids"] if isinstance(body, dict) else []
    results.check("imported count", 6, len(imported), len(imported) == 6)

    print("\n2. Filter by project")
    status, rows = call(base, "GET", f"/api/memories?project={project}")
    results.check("GET ?project=", 200, status, status == 200)
    results.check("row count", 6, len(rows), len(rows) == 6)

    print("\n3. Filter by category")
    status, rows = call(base, "GET", f"/api/memories?project={project}&category=decision")
    results.check("GET ?category=decision", 4, len(rows), len(rows) == 4)

    print("\n4. Read one memory")
    memory_id = imported[0]
    status, single = call(base, "GET", f"/api/memories/{memory_id}")
    results.check("GET /api/memories/{id}", 200, status, status == 200)
    results.check(
        "same id returned",
        memory_id,
        single.get("id") if isinstance(single, dict) else None,
        isinstance(single, dict) and single.get("id") == memory_id,
    )

    print("\n5. Partial update leaves other fields alone")
    status, patched = call(
        base,
        "PATCH",
        f"/api/memories/{memory_id}",
        {"content": "The user service uses PostgreSQL 16 for persistence."},
    )
    results.check("PATCH content", 200, status, status == 200)
    results.check(
        "category preserved",
        "decision",
        patched.get("category") if isinstance(patched, dict) else None,
        isinstance(patched, dict) and patched.get("category") == "decision",
    )

    print("\n6. Supersede an old decision")
    old_id, new_id = imported[3], imported[4]
    status, superseded = call(
        base,
        "PATCH",
        f"/api/memories/{old_id}",
        {"status": "superseded", "superseded_by": new_id},
    )
    results.check("PATCH status+superseded_by", 200, status, status == 200)
    results.check(
        "status is superseded",
        "superseded",
        superseded.get("status") if isinstance(superseded, dict) else None,
        isinstance(superseded, dict) and superseded.get("status") == "superseded",
    )
    status, _ = call(base, "GET", f"/api/memories/{old_id}")
    results.check("old decision still readable", 200, status, status == 200)

    print("\n7. Rule violation: replacement without status")
    status, body = call(
        base, "PATCH", f"/api/memories/{new_id}", {"superseded_by": old_id}
    )
    results.check("PATCH superseded_by only", 422, status, status == 422)

    print("\n8. Rule violation: self-supersede")
    status, body = call(
        base,
        "PATCH",
        f"/api/memories/{new_id}",
        {"status": "superseded", "superseded_by": new_id},
    )
    results.check("PATCH superseded_by=self", 422, status, status == 422)

    print("\n9. Delete a referenced replacement (conflict, not a crash)")
    status, body = call(base, "DELETE", f"/api/memories/{new_id}")
    results.check("DELETE referenced", 409, status, status == 409)
    detail = body.get("detail", "") if isinstance(body, dict) else ""
    results.check("409 names the blocking id", True, old_id in detail, old_id in detail)

    print("\n10. Clear the reference, then delete")
    call(base, "PATCH", f"/api/memories/{old_id}", {"status": "active", "superseded_by": None})
    status, _ = call(base, "DELETE", f"/api/memories/{new_id}")
    results.check("DELETE after clearing", 204, status, status == 204)
    status, _ = call(base, "GET", f"/api/memories/{new_id}")
    results.check("deleted memory is gone", 404, status, status == 404)

    print("\n11. Atomic import: one bad row rejects the batch")
    status, rows_before = call(base, "GET", f"/api/memories?project={project}")
    bad_batch = [
        {**memories[0]},
        {**memories[0], "content": "", "category": "decision"},
        {**memories[0], "category": "vibes"},
    ]
    status, body = call(base, "POST", "/api/memories/import", {"memories": bad_batch})
    results.check("invalid batch rejected", 422, status, status == 422)
    status, rows_after = call(base, "GET", f"/api/memories?project={project}")
    results.check(
        "nothing was written", len(rows_before), len(rows_after),
        len(rows_before) == len(rows_after),
    )

    print("\n12. Unknown ids")
    status, _ = call(base, "GET", "/api/memories/does-not-exist")
    results.check("GET unknown", 404, status, status == 404)
    status, _ = call(base, "DELETE", "/api/memories/does-not-exist")
    results.check("DELETE unknown", 404, status, status == 404)
    status, _ = call(base, "PATCH", "/api/memories/does-not-exist", {"content": "x"})
    results.check("PATCH unknown", 404, status, status == 404)

    print("\n13. Empty and invalid filters")
    status, rows = call(base, "GET", "/api/memories?project=no-such-project")
    results.check("unknown project -> empty list", 200, status, status == 200)
    results.check("empty list length", 0, len(rows), len(rows) == 0)
    status, _ = call(base, "GET", "/api/memories?category=vibes")
    results.check("invalid category -> 422", 422, status, status == 422)

    print("\n14. Validation on create")
    status, _ = call(base, "POST", "/api/memories", {**memories[0], "content": "   "})
    results.check("blank content -> 422", 422, status, status == 422)
    status, _ = call(base, "POST", "/api/memories", {**memories[0], "confidence": 1.5})
    results.check("confidence 1.5 -> 422", 422, status, status == 422)

    return results.summary()


if __name__ == "__main__":
    sys.exit(main())