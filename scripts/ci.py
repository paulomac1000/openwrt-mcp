#!/usr/bin/env python3
"""Local, deterministic quality gate used by agents and CI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def run(*argv: str, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, check=True, env=env)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root / "src")
    run(python, "-m", "compileall", "-q", "src", "tests", "scripts", env=environment)
    run(python, "scripts/check_ai_skills_lock.py", env=environment)
    run(python, "scripts/check_workflows.py", env=environment)
    run(python, "scripts/validate_docs.py", "AGENTS.md", "docs/openwrt-mcp.md", env=environment)
    run(python, "-m", "pytest", "-q", env=environment)
    run(
        python,
        "-m",
        "coverage",
        "run",
        "--branch",
        "-m",
        "pytest",
        "-q",
        "-m",
        "not integration",
        env=environment,
    )
    run(python, "-m", "coverage", "report", "--fail-under=80", env=environment)
    run(python, "scripts/mock_smoke.py", env=environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
