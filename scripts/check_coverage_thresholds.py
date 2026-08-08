#!/usr/bin/env python3
"""Enforce independent line and branch coverage thresholds from coverage XML."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MIN_LINE_PERCENT = 90.0
MIN_BRANCH_PERCENT = 90.0


def _percentage(root: ET.Element, attribute: str) -> float:
    try:
        return float(root.attrib[attribute]) * 100.0
    except (KeyError, ValueError) as exc:
        raise ValueError(f"coverage XML is missing a valid {attribute!r}") from exc


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("coverage.xml")
    root = ET.parse(path).getroot()
    line_percent = _percentage(root, "line-rate")
    branch_percent = _percentage(root, "branch-rate")
    print(f"line coverage: {line_percent:.2f}% (required {MIN_LINE_PERCENT:.2f}%)")
    print(f"branch coverage: {branch_percent:.2f}% (required {MIN_BRANCH_PERCENT:.2f}%)")
    if line_percent < MIN_LINE_PERCENT or branch_percent < MIN_BRANCH_PERCENT:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
