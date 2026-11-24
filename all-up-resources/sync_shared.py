"""Vendor the canonical all-up-resources/caldova_ops package into each deployable unit.

Each target is packaged and deployed on its own (a container, a skill archive,
a hosted-agent source zip), so it needs its own copy. Run this after editing
all-up-resources/caldova_ops; all-up-resources/tests/test_evidence.py fails if a copy has drifted.

  python all-up-resources/sync_shared.py          # write copies
  python all-up-resources/sync_shared.py --check  # exit 1 if any copy differs
"""
from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "all-up-resources" / "caldova_ops"
CODE = ["__init__.py", "evidence.py", "planning.py"]
DATA = ["data/scenario.json", "data/aller-demand-plan.csv"]

# target directory -> files to copy. The harness skill gets code only: its
# evidence must arrive through the caldova-ops toolbox, not a bundled copy.
TARGETS = {
    ROOT / "all-up-resources" / "caldova-ops-mcp" / "caldova_ops": CODE + DATA,
    ROOT / "demo2-equip-harness" / "agents" / "caldova-ops-investigator" / "skills" / "caldova-evidence-package" / "scripts" / "caldova_ops": CODE,
    ROOT / "demo1-build-canvas" / "src" / "caldova-ops-advisor-hosted" / "caldova_ops": CODE + DATA,
    ROOT / "demo3-run-hosted" / "src" / "caldova-ops-runtime" / "caldova_ops": CODE + DATA,
}


# The planner's attachment for demo 2 is the same file as the canonical demand plan.
ATTACHMENT = ROOT / "all-up-resources" / "inputs" / "aller-demand-plan.csv"


def drift() -> list[str]:
    problems = []
    if not ATTACHMENT.exists() or not filecmp.cmp(SOURCE / "data" / "aller-demand-plan.csv", ATTACHMENT, shallow=False):
        problems.append(str(ATTACHMENT.relative_to(ROOT)))
    for target, files in TARGETS.items():
        for rel in files:
            dst = target / rel
            if not dst.exists() or not filecmp.cmp(SOURCE / rel, dst, shallow=False):
                problems.append(str(dst.relative_to(ROOT)))
        extra_data = target / "data"
        if not any(f.startswith("data/") for f in files) and extra_data.exists():
            problems.append(f"{extra_data.relative_to(ROOT)} must not exist (evidence must come from the toolbox)")
    return problems


def sync() -> None:
    ATTACHMENT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE / "data" / "aller-demand-plan.csv", ATTACHMENT)
    for target, files in TARGETS.items():
        for rel in files:
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / rel, dst)
        print(f"synced {target.relative_to(ROOT)} ({len(files)} files)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        problems = drift()
        print("\n".join(problems) or "all vendored copies match all-up-resources/caldova_ops")
        sys.exit(1 if problems else 0)
    sync()
