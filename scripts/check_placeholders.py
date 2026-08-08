#!/usr/bin/env python3
"""Enforce owned, explicit implementation placeholders in production code/tests."""

from __future__ import annotations

import ast
from pathlib import Path

_ALLOWED_PLACEHOLDER = Path("tests/integration/test_real_router_todos.py")
_MARKER = "NOT_IMPLEMENTED"


def _relative(path: Path, root: Path) -> Path:
    return path.resolve().relative_to(root.resolve())


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings: list[str] = []
    placeholder_count = 0

    for source_root in (root / "src", root / "tests"):
        for path in sorted(source_root.rglob("*.py")):
            relative = _relative(path, root)
            text = path.read_text(encoding="utf-8")

            if relative.parts[0] == "src" and ("TODO" in text or "FIXME" in text):
                findings.append(f"{relative}: executable source contains TODO/FIXME")

            if _MARKER not in text:
                continue
            count = text.count(_MARKER)
            placeholder_count += count
            if relative != _ALLOWED_PLACEHOLDER:
                findings.append(f"{relative}: {_MARKER} is not an approved placeholder")
                continue

            if count != 1:
                findings.append(f"{relative}: expected exactly one {_MARKER} marker, found {count}")
            tree = ast.parse(text, filename=str(relative))
            raises_not_implemented = any(
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "NotImplementedError"
                for node in ast.walk(tree)
            )
            if not raises_not_implemented:
                findings.append(f"{relative}: placeholder must raise NotImplementedError")
            if "pytest.mark.skip" not in text:
                findings.append(f"{relative}: placeholder must be an explicit skipped test")

    if placeholder_count != 1:
        findings.append(
            f"repository must contain exactly one owned {_MARKER} placeholder; "
            f"found {placeholder_count}"
        )

    if findings:
        print("placeholder policy failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print(f"placeholder policy passed: {_ALLOWED_PLACEHOLDER} is the only owned placeholder")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
