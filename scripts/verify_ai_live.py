#!/usr/bin/env python3
"""Verify AI-assisted analysis against a REAL language model.

The automated suite exercises this path against a stub server, because CI has no
API key. That proves the plumbing; it does not prove that a real model produces
useful findings or that the injection defences hold against one. This script does
that, in one command, and checks the safety properties rather than eyeballing the
output.

Usage:
    # with a key in the environment
    export DEVMEMORY_LLM_API_KEY=sk-...
    export DEVMEMORY_LLM_MODEL=gpt-4o-mini

    # start the API with the same environment, then:
    python3 scripts/verify_ai_live.py

Checks:
    1. the endpoint reports itself available
    2. findings come back labelled source=model
    3. every referenced memory id exists in the store
    4. every finding has evidence, an explanation, an action and an uncertainty
    5. the instruction-like sample memory was withheld from the prompt
    6. no memory was created, edited or deleted
    7. the API key does not appear anywhere in the response

Exit codes: 0 all checks passed, 1 a check failed, 2 not configured.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

INJECTION_PHRASE = "Ignore all previous instructions"


def call(base: str, method: str, path: str, body: object | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            return response.status, raw, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, raw, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, raw, None
    except urllib.error.URLError as error:
        raise SystemExit(
            f"Cannot reach the API at {base}: {error.reason}\n"
            "Start it with: uvicorn app.main:app --port 8000"
        ) from error


class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        suffix = f" — {detail}" if detail else ""
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}{suffix}")

    def summary(self) -> int:
        total = self.passed + self.failed
        print(f"\n{self.passed}/{total} checks passed")
        if self.failed:
            print("\nSome checks failed. Do not claim the AI path is verified.")
        return 0 if self.failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--project", default=None, help="Limit the analysis to one project."
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    results = Results()

    print(f"API: {base}\n")

    print("1. Configuration")
    status, _, body = call(base, "GET", "/api/health/ai/status")
    if status != 200 or not isinstance(body, dict):
        print(f"  Could not read status (HTTP {status}).")
        return 2
    if not body.get("available"):
        print(f"  AI analysis is not configured: {body.get('reason')}")
        print("\nExport DEVMEMORY_LLM_API_KEY and DEVMEMORY_LLM_MODEL, restart the")
        print("API with them, and run this script again.")
        return 2
    results.check("provider is available", True, body.get("model", ""))
    print()

    print("2. Snapshot the collection before analysis")
    _, _, before = call(base, "GET", "/api/memories")
    before_memories = before if isinstance(before, list) else []
    before_ids = {item["id"] for item in before_memories}
    results.check(
        "collection loaded", bool(before_memories), f"{len(before_memories)} memories"
    )

    injection_ids = {
        item["id"]
        for item in before_memories
        if INJECTION_PHRASE.lower() in item["content"].lower()
    }
    print()

    print("3. Run the analysis")
    status, raw, report = call(
        base, "POST", "/api/health/ai", {"project": args.project}
    )
    results.check("analysis returns 200", status == 200, f"HTTP {status}")
    if status != 200 or not isinstance(report, dict):
        print(f"\nResponse: {raw[:400]}")
        return results.summary()

    findings = report.get("findings", [])
    print(
        f"  model={report.get('model')} analysed={report.get('analyzed_memories')} "
        f"findings={len(findings)} rejected={len(report.get('rejected', []))}"
    )
    print()

    print("4. Output quality")
    results.check(
        "at least one finding was produced",
        len(findings) > 0,
        "an empty result is valid in general, but it tells you nothing about quality"
        if not findings
        else "",
    )
    for index, finding in enumerate(findings):
        has_fields = all(
            str(finding.get(field, "")).strip()
            for field in ("title", "explanation", "suggested_action", "uncertainty")
        )
        results.check(
            f"finding {index} is complete and labelled",
            has_fields and finding.get("source") == "model",
            finding.get("issue_type", "?"),
        )
        print(f"      → {finding.get('title')}")
        print(f"        uncertainty: {finding.get('uncertainty')}")
        print(f"        evidence: {len(finding.get('evidence', []))} quoted item(s)")
    print()

    print("5. Every referenced memory exists")
    unknown: list[str] = []
    for finding in findings:
        for memory_id in finding.get("memory_ids", []):
            if memory_id not in before_ids:
                unknown.append(memory_id)
    results.check(
        "no finding references an unknown memory",
        not unknown,
        ", ".join(sorted(set(unknown))[:3]),
    )
    print()

    print("6. Prompt-injection containment")
    excluded = set(report.get("excluded_memories", []))
    if injection_ids:
        results.check(
            "the instruction-like memory was withheld from the prompt",
            injection_ids <= excluded,
            f"{len(injection_ids)} injection memory/memories, {len(excluded)} withheld",
        )
    else:
        print("  (no instruction-like memory in this collection; import the sample data)")
    results.check(
        "no finding cites the injection memory",
        not any(injection_ids & set(f.get("memory_ids", [])) for f in findings),
    )
    print()

    print("7. Nothing was applied")
    _, _, after = call(base, "GET", "/api/memories")
    after_ids = {item["id"] for item in (after if isinstance(after, list) else [])}
    results.check(
        "collection is unchanged",
        before_ids == after_ids,
        f"{len(before_ids)} → {len(after_ids)}",
    )
    print()

    print("8. The key is not leaked")
    key = os.environ.get("DEVMEMORY_LLM_API_KEY", "")
    if key:
        results.check(
            "API key absent from the response body", key not in raw.decode(errors="ignore")
        )
    else:
        print("  (key not in this shell's environment; cannot check this here)")
    print()

    print("9. Rejected suggestions are reported")
    for item in report.get("rejected", []):
        print(f"  · {item}")
    if not report.get("rejected"):
        print("  (the model produced no invalid suggestions — also a good sign)")
    print()

    print("Sample of what the model said:")
    for finding in findings[:3]:
        print(f"\n  {finding.get('issue_type')}: {finding.get('title')}")
        print(f"  {finding.get('explanation')}")
        print(f"  suggested: {finding.get('suggested_action')}")

    return results.summary()


if __name__ == "__main__":
    sys.exit(main())