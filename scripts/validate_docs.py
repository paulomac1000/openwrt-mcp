#!/usr/bin/env python3
"""Validate the repository's governed Markdown documents."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
REQUIRED = {"description", "doc_id", "type", "status", "rigor", "owners"}


def validate(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    if not match:
        return [f"{path}: missing YAML frontmatter"]
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        return [f"{path}: frontmatter must be a mapping"]
    findings = [f"{path}: missing {name}" for name in sorted(REQUIRED - metadata.keys())]
    body = text[match.end() :]
    if len(re.findall(r"^#\s+\S", body, re.M)) != 1:
        findings.append(f"{path}: expected exactly one H1")
    if metadata.get("rigor") in {"operational", "normative"}:
        if not metadata.get("verification"):
            findings.append(f"{path}: missing explicit verification")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    findings = [item for path in args.inputs for item in validate(path)]
    for finding in findings:
        print(finding)
    print(f"documentation findings: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
