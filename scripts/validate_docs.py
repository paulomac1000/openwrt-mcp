#!/usr/bin/env python3
"""Validate the local AFDS subset without executing repository content."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

REQUIRED = {"description", "doc_id", "type", "status", "rigor", "owners", "verification"}
VALID_TYPES = {"workflow", "reference", "system", "guide", "decision", "contract"}
VALID_STATUS = {"draft", "active", "evolving", "deprecated", "archived"}
VALID_RIGOR = {"informative", "operational", "normative"}
AUTOMATION_FIELDS = {
    "last_verified",
    "fitness_score",
    "semantic_hash",
    "dependency_versions",
    "backlinks",
}
MAX_BYTES = 512_000
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


def confined_markdown(root: Path, candidate: Path) -> Path:
    if candidate.is_symlink():
        raise ValueError("symlink input is forbidden")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("path escapes repository root")
    if not resolved.is_file() or resolved.suffix.lower() != ".md":
        raise ValueError("expected regular Markdown file")
    if resolved.stat().st_size > MAX_BYTES:
        raise ValueError("document exceeds byte limit")
    return resolved


def validate(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    try:
        resolved = confined_markdown(root, path)
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"{path}: {exc}"]
    match = FRONTMATTER.match(text)
    if match is None:
        return [f"{path}: missing YAML frontmatter"]
    try:
        metadata: Any = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return [f"{path}: invalid YAML: {exc}"]
    if not isinstance(metadata, dict):
        return [f"{path}: frontmatter must be a mapping"]
    missing = sorted(REQUIRED - {key for key, value in metadata.items() if value})
    if missing:
        errors.append(f"{path}: missing fields: {', '.join(missing)}")
    if metadata.get("type") not in VALID_TYPES:
        errors.append(f"{path}: invalid type")
    if metadata.get("status") not in VALID_STATUS:
        errors.append(f"{path}: invalid status")
    if metadata.get("rigor") not in VALID_RIGOR:
        errors.append(f"{path}: invalid rigor")
    doc_id = metadata.get("doc_id")
    if not isinstance(doc_id, str) or not doc_id.startswith(f"{metadata.get('type')}."):
        errors.append(f"{path}: doc_id prefix does not match type")
    authored = sorted(AUTOMATION_FIELDS.intersection(metadata))
    if authored:
        errors.append(f"{path}: automation-owned fields: {', '.join(authored)}")
    body = text[match.end():]
    headings = HEADING.findall(body)
    if sum(level == "#" for level, _ in headings) != 1:
        errors.append(f"{path}: expected exactly one H1")
    return errors


def main() -> int:
    root = Path.cwd().resolve()
    selected = [Path(arg) for arg in sys.argv[1:]]
    if not selected:
        selected = sorted(Path("docs").rglob("*.md"))
    errors = [error for path in selected for error in validate(root, path)]
    for error in errors:
        print(error, file=sys.stderr)
    print(f"validated {len(selected)} documents; findings: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
