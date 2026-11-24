"""Shared paths for the offline test suite (python -m unittest discover -s all-up-resources/tests)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "all-up-resources"
MCP = SHARED / "caldova-ops-mcp"
SKILL = ROOT / "demo2-equip-harness" / "agents" / "caldova-ops-investigator" / "skills" / "caldova-evidence-package"
RUNTIME = ROOT / "demo3-run-hosted" / "src" / "caldova-ops-runtime"
DEMAND = SHARED / "inputs" / "aller-demand-plan.csv"

if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
