#!/usr/bin/env python3
"""Candidate-tree workflow policy diagnostics; not independent approval."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

FULL_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
_ALLOWED_PROFILES = {"pull-request", "trusted-ci", "protected-release"}


def _load_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def main() -> int:
    findings: list[str] = []
    workflow_paths = sorted(Path(".github/workflows").glob("*.yml"))
    policy_path = Path(".github/workflow-policy.yaml")
    policy = _load_mapping(policy_path) if policy_path.exists() else {}
    configured = policy.get("workflows", {})
    if policy.get("schema_version") != 1 or not isinstance(configured, dict):
        findings.append(f"{policy_path}: invalid or missing workflow policy map")
        configured = {}

    expected_paths = {path.as_posix() for path in workflow_paths}
    configured_paths = set(configured)
    if expected_paths != configured_paths:
        findings.append(
            f"{policy_path}: governed workflow mismatch: "
            f"missing={sorted(expected_paths - configured_paths)}, "
            f"orphaned={sorted(configured_paths - expected_paths)}"
        )

    for path in workflow_paths:
        profile = configured.get(path.as_posix())
        if profile not in _ALLOWED_PROFILES:
            findings.append(f"{path}: missing or invalid policy profile {profile!r}")
        data = _load_mapping(path)
        if not data:
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
            if profile == "protected-release" and job.get("permissions"):
                permissions = job.get("permissions", {})
                if isinstance(permissions, dict) and any(
                    value == "write" for value in permissions.values()
                ):
                    if not job.get("environment"):
                        findings.append(
                            f"{path}:{job_name}: privileged release job needs environment"
                        )
                    if not job.get("needs"):
                        findings.append(
                            f"{path}:{job_name}: privileged release job needs prior validation"
                        )
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
                    if profile == "protected-release":
                        findings.append(
                            f"{path}:{job_name}: protected release must not checkout source"
                        )
                if profile == "protected-release":
                    run = str(step.get("run", ""))
                    if re.search(r"(?:^|\n)\s*docker\s+(?:build|run)\b", run):
                        findings.append(
                            f"{path}:{job_name}: protected release must not build/run image"
                        )

    for finding in findings:
        print(finding)
    print(f"workflow findings: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
