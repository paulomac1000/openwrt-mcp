#!/usr/bin/env python3
"""Validate the immutable ai-skills standards reference."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

EXPECTED = "661ff01a5e70d58d6c94a12545b24647e52063ed"


def main() -> int:
    data = yaml.safe_load(Path("standards-lock.yaml").read_text(encoding="utf-8"))
    revision = data.get("source_revision") if isinstance(data, dict) else None
    if revision != EXPECTED or not re.fullmatch(r"[0-9a-f]{40}", str(revision)):
        raise SystemExit("standards-lock.yaml does not pin the reviewed ai-skills SHA")
    skills = data.get("skills", {})
    required = {
        "mcp-server-architect",
        "afds-doc-writer",
        "agents-md-architect",
        "ci-cd-architect",
    }
    if not isinstance(skills, dict) or set(skills) != required:
        raise SystemExit("standards-lock.yaml has an incomplete skill catalog")
    print(f"ai-skills lock: {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
