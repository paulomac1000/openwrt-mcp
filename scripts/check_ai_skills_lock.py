#!/usr/bin/env python3
"""Fail when the adopted ai-skills revision or version is incomplete."""

from __future__ import annotations

from pathlib import Path

import yaml

EXPECTED_REVISION_LENGTH = 40


def main() -> int:
    data = yaml.safe_load(Path("standards-lock.yaml").read_text(encoding="utf-8"))
    skills = data.get("skills", {})
    required = {"mcp-server-architect", "afds-doc-writer", "agents-md-architect", "ci-cd-architect"}
    if set(skills) != required:
        raise SystemExit("standards-lock.yaml must pin the four adopted skills")
    revision = data.get("source_revision")
    if not isinstance(revision, str) or len(revision) != EXPECTED_REVISION_LENGTH:
        raise SystemExit("skill revision must be a full 40-character SHA")
    for name, item in skills.items():
        if not item.get("version") or not item.get("normative_entrypoint"):
            raise SystemExit(f"incomplete skill lock: {name}")
    print(f"ai-skills lock valid: {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
