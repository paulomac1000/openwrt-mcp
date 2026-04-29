"""
Unit test configuration for OpenWRT-MCP.
"""

import pytest
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))