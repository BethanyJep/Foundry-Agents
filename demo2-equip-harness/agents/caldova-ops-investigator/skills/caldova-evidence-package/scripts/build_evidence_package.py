#!/usr/bin/env python3
"""Build the Caldova evidence package from a verified evidence bundle.

Runs inside the Copilot harness sandbox (standard library only):

  python3 build_evidence_package.py --bundle work/evidence/bundle.json \
      [--demand aller-demand-plan.csv] --out work/out

Writes plan.json, caldova-evidence-package.md and allocation-plan.csv, then
prints a JSON summary. Exits with code 2 and a plain-language message when an
input is missing or has been altered, so the agent can fix it and retry.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from caldova_ops.evidence import EvidenceError, verify_bundle  # noqa: E402
from caldova_ops.planning import (  # noqa: E402
    PlanningError, build_plan, read_demand_plan, render_csv, render_markdown,
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(2)


def main(argv=None) -> dict:
    parser = argparse.ArgumentParser(description="Build the Caldova evidence package.")
    parser.add_argument("--bundle", required=True, type=Path, help="verbatim get_evidence_bundle JSON")
    parser.add_argument("--demand", type=Path, help="planner demand plan CSV (optional)")
    parser.add_argument("--out", required=True, type=Path, help="output folder")
    args = parser.parse_args(argv)

    try:
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"No evidence bundle at {args.bundle}. Call the caldova_ops tool get_evidence_bundle "
             "and save its JSON result unmodified to that path.")
    except json.JSONDecodeError as exc:
        fail(f"{args.bundle} is not valid JSON ({exc}). Save the tool result exactly as returned.")

    try:
        documents = verify_bundle(bundle)
    except EvidenceError as exc:
        fail(str(exc))

    demand_rows = None
    if args.demand:
        if not args.demand.exists():
            fail(f"Demand plan {args.demand} not found. Check the attachment path in the workspace, "
                 "or run without --demand to use the DISRUPT-001 average.")
        try:
            demand_rows = read_demand_plan(args.demand)
        except (PlanningError, ValueError, KeyError) as exc:
            fail(f"Demand plan {args.demand} could not be read: {exc}")

    plan = build_plan(documents, demand_rows)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (args.out / "caldova-evidence-package.md").write_text(
        render_markdown(plan, bundle["bundle_sha256"], "caldova-evidence-package skill"), encoding="utf-8")
    (args.out / "allocation-plan.csv").write_text(render_csv(plan), encoding="utf-8")

    summary = {
        "plan_id": plan["plan_id"],
        "basis": plan["basis"],
        "totals": plan["totals"],
        "residual_weeks": [w["week"] for w in plan["weeks"] if w["residual_gap"]],
        "blocked_suppliers": [s["supplier"] for s in plan["suppliers"] if not s["eligible_to_recommend"]],
        "approvals_required": plan["approvals_required"],
        "files": [str(args.out / n) for n in ("caldova-evidence-package.md", "allocation-plan.csv", "plan.json")],
        "status": plan["status"],
    }
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
