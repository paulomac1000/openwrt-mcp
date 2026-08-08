#!/usr/bin/env python3
"""Local deterministic quality gate used by agents and CI."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def run(*argv: str, env: dict[str, str]) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, check=True, env=env)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root / "src")
    python = sys.executable
    run(python, "-m", "compileall", "-q", "src", "tests", "scripts", env=environment)
    run(python, "scripts/check_ai_skills_lock.py", env=environment)
    run(python, "scripts/check_workflows.py", env=environment)
    run(
        python,
        "scripts/validate_docs.py",
        "AGENTS.md",
        "docs/openwrt-mcp.md",
        "docs/production-acceptance.md",
        env=environment,
    )
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
    run(python, "-m", "coverage", "report", "--fail-under=90", env=environment)
    run(python, "-m", "coverage", "xml", "-o", "coverage.xml", env=environment)
    run(python, "scripts/check_coverage_thresholds.py", "coverage.xml", env=environment)
    mock_environment = dict(environment)
    if importlib.util.find_spec("mcp") is None:
        mock_environment["PYTHONPATH"] = os.pathsep.join(
            (str(root / "tests" / "fakes"), str(root / "src"))
        )
        print(
            "official MCP SDK unavailable; mock_smoke uses the test-only SDK fake",
            flush=True,
        )
    run(python, "scripts/mock_smoke.py", env=mock_environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
