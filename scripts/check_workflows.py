#!/usr/bin/env python3
"""Candidate-tree workflow policy diagnostics; not independent approval."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

FULL_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def main() -> int:
    findings: list[str] = []
    for path in sorted(Path(".github/workflows").glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            findings.append(f"{path}: workflow must be a mapping")
            continue
        if data.get("permissions") not in ({"contents": "read"}, "read-all"):
            findings.append(f"{path}: top-level permissions must be read-only")
        if not data.get("concurrency"):
            findings.append(f"{path}: missing concurrency")
        jobs = data.get("jobs", {})
        if not isinstance(jobs, dict):
            findings.append(f"{path}: jobs must be a mapping")
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if not isinstance(job.get("timeout-minutes"), int):
                findings.append(f"{path}:{job_name}: missing numeric timeout-minutes")
            for step in job.get("steps", []):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if uses and not FULL_SHA.fullmatch(str(uses)):
                    findings.append(f"{path}:{job_name}: mutable action reference {uses}")
                if str(uses).startswith("actions/checkout@"):
                    if step.get("with", {}).get("persist-credentials") is not False:
                        findings.append(
                            f"{path}:{job_name}: checkout must disable persisted credentials"
                        )
    for finding in findings:
        print(finding)
    print(f"workflow findings: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
