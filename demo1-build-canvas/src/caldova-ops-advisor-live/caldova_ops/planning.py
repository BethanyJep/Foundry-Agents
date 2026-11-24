"""Deterministic planning and policy checks for the Caldova capacity disruption.

The same module runs in three places:
  * Demo 2: inside the Copilot harness sandbox, called by the skill script.
  * Demo 3: inside the hosted agent, as a tool and as the submission gate.
  * Tests: locally, with no Azure dependency.

Standard library only, so it runs anywhere Python 3.9+ runs.
Every number in a plan carries the source IDs it came from.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

Docs = Dict[str, Any]

# Source IDs any recommendation must cite, because its numbers and limits come from them.
REQUIRED_CITATIONS = ("DISRUPT-001", "CAP-001", "CAP-POLICY", "DIST-001", "DIST-POLICY")


class PlanningError(Exception):
    pass


# --------------------------------------------------------------------------- inputs

def read_demand_plan(source: Union[str, Path]) -> List[Dict[str, Any]]:
    """Read the planner's weekly demand file (path or CSV text).

    Columns: week, week_start, forecast_units, internal_capacity_units.
    The gap for a week is forecast minus internal capacity, floored at zero.
    """
    text = Path(source).read_text(encoding="utf-8") if _looks_like_path(source) else str(source)
    reader = csv.DictReader(io.StringIO(text.strip()))
    required = {"week", "week_start", "forecast_units", "internal_capacity_units"}
    if not reader.fieldnames or not required.issubset({f.strip() for f in reader.fieldnames}):
        raise PlanningError(
            f"Demand plan needs columns {sorted(required)}; found {reader.fieldnames}."
        )
    rows = []
    for raw in reader:
        row = {k.strip(): (v or "").strip() for k, v in raw.items()}
        forecast = int(row["forecast_units"])
        internal = int(row["internal_capacity_units"])
        rows.append({
            "week": int(row["week"]),
            "week_start": row["week_start"],
            "forecast_units": forecast,
            "internal_capacity_units": internal,
            "gap": max(0, forecast - internal),
        })
    if not rows:
        raise PlanningError("Demand plan has no rows.")
    return sorted(rows, key=lambda r: r["week"])


def _looks_like_path(source: Union[str, Path]) -> bool:
    if isinstance(source, Path):
        return True
    return "\n" not in source and source.lower().endswith(".csv")


def flat_gaps_from_brief(docs: Docs) -> List[Dict[str, Any]]:
    brief = docs["DISRUPT-001"]["data"]
    return [
        {"week": w, "week_start": "", "forecast_units": None, "internal_capacity_units": None,
         "gap": brief["average_weekly_gap"]}
        for w in range(1, brief["weeks"] + 1)
    ]


# --------------------------------------------------------------------------- assessments

def assess_suppliers(docs: Docs) -> List[Dict[str, Any]]:
    """Apply CAP-001, RISK-001 and the RISK-POLICY rubric to every supplier."""
    observations = {o["supplier"]: o for o in docs["RISK-001"]["data"]["observations"]}
    assessed = []
    for supplier in docs["CAP-001"]["data"]["suppliers"]:
        name = supplier["name"]
        obs = observations.get(name, {})
        reasons = []
        if supplier["qualification"] != "complete":
            reasons.append({"reason": f"qualification review {supplier['qualification']}",
                            "sources": ["CAP-001", "RISK-001"]})
        if obs.get("overdue_corrective_actions", 0) > 0:
            reasons.append({"reason": f"{obs['overdue_corrective_actions']} overdue corrective actions",
                            "sources": ["RISK-001"]})
        elevated = bool(reasons)
        assessed.append({
            "supplier": name,
            "available_units_per_week": supplier["available_units_per_week"],
            "qualification": supplier["qualification"],
            "overdue_corrective_actions": obs.get("overdue_corrective_actions"),
            "risk": "elevated" if elevated else "routine monitoring",
            "risk_sources": ["RISK-001", "RISK-POLICY"],
            "eligible_to_recommend": not elevated,
            "blockers": reasons,
            "escalate_to": docs["RISK-POLICY"]["data"]["escalate_to"] if elevated else [],
        })
    return assessed


def route_register(docs: Docs) -> Dict[str, List[Dict[str, Any]]]:
    routes = docs["DIST-001"]["data"]["routes"]
    assessed = sorted((r for r in routes if r["assessed"]), key=lambda r: r["transit_days"])
    return {"assessed": assessed, "unassessed": [r for r in routes if not r["assessed"]]}


def allocate_to_routes(units: int, assessed_routes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Fill the fastest documented route up to its cap, then the next."""
    remaining = units
    allocation = {}
    for route in assessed_routes:
        take = min(remaining, route["max_units_per_week"])
        allocation[route["name"]] = take
        remaining -= take
    return {"routes": allocation, "unrouted": remaining}


# --------------------------------------------------------------------------- plan

def build_plan(docs: Docs, demand_rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Recommend how to cover the gap with eligible capacity and documented routes."""
    basis = "planner demand file" if demand_rows else "DISRUPT-001 weekly average"
    weeks_in = demand_rows or flat_gaps_from_brief(docs)
    suppliers = assess_suppliers(docs)
    eligible = [s for s in suppliers if s["eligible_to_recommend"]]
    blocked = [s for s in suppliers if not s["eligible_to_recommend"]]
    routes = route_register(docs)

    weeks = []
    for row in weeks_in:
        remaining = row["gap"]
        supplier_alloc = []
        for s in eligible:
            take = min(remaining, s["available_units_per_week"])
            if take:
                supplier_alloc.append({"supplier": s["supplier"], "units": take})
            remaining -= take
        covered = row["gap"] - remaining
        routed = allocate_to_routes(covered, routes["assessed"])
        weeks.append({
            "week": row["week"],
            "week_start": row["week_start"],
            "gap": row["gap"],
            "supplier_allocations": supplier_alloc,
            "covered": covered,
            "routes": routed["routes"],
            "unrouted": routed["unrouted"],
            "residual_gap": remaining,
        })

    total_gap = sum(w["gap"] for w in weeks)
    total_covered = sum(w["covered"] for w in weeks)
    residual_weeks = [w["week"] for w in weeks if w["residual_gap"]]

    # What-if: Quality clears every blocked supplier. Shows whether routes, not
    # capacity, become the constraint. A scenario, never a recommendation.
    route_capacity = sum(r["max_units_per_week"] for r in routes["assessed"])
    what_if = []
    for w in weeks:
        extra = w["residual_gap"]
        blocked_capacity = sum(s["available_units_per_week"] for s in blocked)
        could_cover = min(extra, blocked_capacity)
        needs_routing = w["covered"] + could_cover
        what_if.append({
            "week": w["week"],
            "additional_units_if_cleared": could_cover,
            "units_to_route": needs_routing,
            "documented_route_capacity": route_capacity,
            "route_shortfall": max(0, needs_routing - route_capacity),
        })

    packet = docs["PACKET-001"]["data"]
    owners = docs["PACKET-POLICY"]["data"]["item_owners"]
    packet_review = {
        "packet_id": packet["packet_id"],
        "proposed_supplier": packet["proposed_supplier"],
        "status": "hold: incomplete, not approved",
        "missing": [{"item": item, "owner": owners.get(item, "Change owner")} for item in packet["missing"]],
        "sources": ["PACKET-001", "PACKET-POLICY"],
    }

    contract = docs["CONTRACT-AR-001"]["data"]
    approvals = [
        {"decision": "Commit " + (" and ".join(s["supplier"] for s in eligible) or "supplier") + " capacity",
         "approvers": docs["CAP-POLICY"]["data"]["supplier_commitment_approvers"],
         "sources": ["CAP-POLICY"]},
        {"decision": "Change route allocations (Cedar, Birch)",
         "approvers": docs["DIST-POLICY"]["data"]["allocation_change_approvers"],
         "sources": ["DIST-POLICY"]},
    ]
    escalations = [
        {"item": f"{s['supplier']}: elevated risk ({'; '.join(b['reason'] for b in s['blockers'])})",
         "to": s["escalate_to"], "sources": ["RISK-001", "RISK-POLICY"]}
        for s in blocked
    ]
    escalations += [
        {"item": f"Route {r['name']}: not assessed, no transit or allocation values",
         "to": [docs["DIST-POLICY"]["data"]["missing_route_evidence_owner"]],
         "sources": ["DIST-001", "DIST-POLICY"]}
        for r in routes["unassessed"]
    ]
    if residual_weeks:
        escalations.append({
            "item": (f"{total_gap - total_covered:,} units of the gap remain uncovered "
                     f"(weeks {', '.join(str(w) for w in residual_weeks)}) after eligible capacity"),
            "to": ["Manufacturing Operations", "Procurement"],
            "sources": ["DISRUPT-001", "CAP-001"],
        })

    plan = {
        "scenario": "caldova-aller-capacity-disruption",
        "status": "recommendation only - no operational action taken",
        "basis": basis,
        "weeks": weeks,
        "totals": {"gap": total_gap, "covered": total_covered, "residual_gap": total_gap - total_covered},
        "suppliers": suppliers,
        "routes": routes,
        "what_if_blocked_suppliers_cleared": what_if,
        "packet_review": packet_review,
        "contract_watch": {
            "supplier": contract["supplier"],
            "covered": contract["covered"],
            "requires_written_authorization": contract["requires_written_authorization"],
            "authorization_owner": contract["authorization_owner"],
            "sources": ["CONTRACT-AR-001"],
        },
        "approvals_required": approvals,
        "escalations": escalations,
        "sources_used": sorted(docs),
    }
    plan["plan_id"] = "PLAN-" + _short_hash({k: plan[k] for k in ("basis", "weeks", "totals")})
    return plan


def proposal_from_plan(plan: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    """The submission shape the hosted agent's gate accepts, prefilled from a plan."""
    return {
        "case_id": case_id,
        "weeks": [
            {"week": w["week"], "supplier": a["supplier"], "units": a["units"],
             "routes": {k: v for k, v in w["routes"].items() if v}}
            for w in plan["weeks"] for a in w["supplier_allocations"]
        ],
        "cited_sources": list(REQUIRED_CITATIONS) + ["RISK-001", "RISK-POLICY"],
    }


# --------------------------------------------------------------------------- policy gate

def validate_proposal(docs: Docs, proposal: Dict[str, Any],
                      demand_rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Check a proposed allocation against the evidence and policies in code.

    A model can be talked into anything; this function can't. It never approves:
    an accepted proposal becomes 'pending_human_approval'.
    """
    violations: List[Dict[str, Any]] = []
    weeks_in = {r["week"]: r for r in (demand_rows or flat_gaps_from_brief(docs))}
    suppliers = {s["supplier"].lower(): s for s in assess_suppliers(docs)}
    routes_all = {r["name"].lower(): r for r in docs["DIST-001"]["data"]["routes"]}

    def flag(week, message, sources):
        violations.append({"week": week, "violation": message, "sources": sources})

    entries = proposal.get("weeks") or []
    if not entries:
        flag(None, "Proposal contains no weekly allocations.", [])

    per_week_units: Dict[int, int] = {}
    per_week_routes: Dict[int, Dict[str, int]] = {}
    for entry in entries:
        week = entry.get("week")
        units = entry.get("units")
        name = str(entry.get("supplier", "")).strip()
        if week not in weeks_in:
            flag(week, f"Week {week} is outside the disruption window (weeks {min(weeks_in)}-{max(weeks_in)}).",
                 ["DISRUPT-001"])
            continue
        if not isinstance(units, int) or units < 0:
            flag(week, f"Units must be a non-negative whole number; got {units!r}.", [])
            continue
        supplier = suppliers.get(name.lower())
        if supplier is None:
            flag(week, f"Supplier '{name}' is not in the capacity register.", ["CAP-001"])
        else:
            if not supplier["eligible_to_recommend"]:
                reasons = "; ".join(b["reason"] for b in supplier["blockers"])
                flag(week, f"{supplier['supplier']} cannot be committed: elevated risk ({reasons}). "
                           f"Escalate to {' and '.join(supplier['escalate_to'])}.",
                     ["CAP-001", "CAP-POLICY", "RISK-001", "RISK-POLICY"])
            if units > supplier["available_units_per_week"]:
                flag(week, f"{supplier['supplier']} {units} units exceeds available "
                           f"{supplier['available_units_per_week']} per week.", ["CAP-001"])
        per_week_units[week] = per_week_units.get(week, 0) + units
        for route_name, route_units in (entry.get("routes") or {}).items():
            per_week_routes.setdefault(week, {})
            key = str(route_name).strip()
            per_week_routes[week][key] = per_week_routes[week].get(key, 0) + int(route_units)

    for week, units in sorted(per_week_units.items()):
        gap = weeks_in[week]["gap"]
        if units > gap:
            flag(week, f"Week {week} commits {units} units but the documented gap is {gap}.",
                 ["DISRUPT-001"])
        routed = per_week_routes.get(week, {})
        for route_name, route_units in routed.items():
            route = routes_all.get(route_name.lower())
            if route is None:
                flag(week, f"Route '{route_name}' is not in the route register.", ["DIST-001"])
            elif not route["assessed"]:
                flag(week, f"Route {route['name']} has not been assessed; no allocation values exist. "
                           "Escalate to Supply Chain Operations.", ["DIST-001", "DIST-POLICY"])
            elif route_units > route["max_units_per_week"]:
                flag(week, f"Route {route['name']} {route_units} units exceeds its maximum allocation of "
                           f"{route['max_units_per_week']} per week.", ["DIST-001"])
        if sum(routed.values()) != units:
            flag(week, f"Week {week}: {units} units committed but {sum(routed.values())} routed; "
                       "every unit needs a documented route.", ["DIST-001"])

    cited = {s.strip().upper() for s in proposal.get("cited_sources") or []}
    missing = [s for s in REQUIRED_CITATIONS if s not in cited]
    if missing:
        flag(None, f"Recommendation must cite {', '.join(missing)}.", missing)

    covered = {w: min(per_week_units.get(w, 0), r["gap"]) for w, r in weeks_in.items()}
    open_gap = {w: r["gap"] - covered[w] for w, r in weeks_in.items() if r["gap"] - covered[w] > 0}
    accepted = not violations
    return {
        "accepted": accepted,
        "status": "pending_human_approval" if accepted else "rejected_by_policy_gate",
        "violations": violations,
        "required_approvals": [
            {"decision": "Commit supplier capacity",
             "approvers": docs["CAP-POLICY"]["data"]["supplier_commitment_approvers"], "sources": ["CAP-POLICY"]},
            {"decision": "Change route allocations",
             "approvers": docs["DIST-POLICY"]["data"]["allocation_change_approvers"], "sources": ["DIST-POLICY"]},
        ] if accepted else [],
        "open_gap_by_week": open_gap,
        "note": "The gate never approves. Accepted proposals wait for the named human approvers.",
    }


# --------------------------------------------------------------------------- rendering

def render_csv(plan: Dict[str, Any]) -> str:
    route_names = [r["name"] for r in plan["routes"]["assessed"]]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["week", "week_start", "gap", "supplier", "supplier_units",
                     *[f"{r.lower()}_units" for r in route_names], "unrouted", "residual_gap", "sources"])
    for w in plan["weeks"]:
        allocs = w["supplier_allocations"] or [{"supplier": "", "units": 0}]
        for a in allocs:
            writer.writerow([w["week"], w["week_start"], w["gap"], a["supplier"], a["units"],
                             *[w["routes"].get(r, 0) for r in route_names],
                             w["unrouted"], w["residual_gap"], "DISRUPT-001;CAP-001;DIST-001"])
    return out.getvalue()


def render_markdown(plan: Dict[str, Any], bundle_sha256: str = "", generated_by: str = "") -> str:
    t = plan["totals"]
    eligible = [s for s in plan["suppliers"] if s["eligible_to_recommend"]]
    blocked = [s for s in plan["suppliers"] if not s["eligible_to_recommend"]]
    routes = plan["routes"]["assessed"]
    route_names = [r["name"] for r in routes]
    shortfalls = [w for w in plan["what_if_blocked_suppliers_cleared"] if w["route_shortfall"]]
    residual_weeks = [w for w in plan["weeks"] if w["residual_gap"]]

    lines = [
        "# Caldova evidence package: ALLER capacity disruption [DISRUPT-001]",
        "",
        "> Synthetic training data. This package is a recommendation for human decision. "
        "No capacity, shipment, allocation, contract or approval action has been taken.",
        "",
        f"- Plan ID: `{plan['plan_id']}`",
        f"- Basis for weekly gaps: {plan['basis']}",
    ]
    if bundle_sha256:
        lines.append(f"- Evidence bundle SHA-256: `{bundle_sha256}` (verified before planning)")
    if generated_by:
        lines.append(f"- Generated by: {generated_by}")
    lines += [
        "",
        "## Recommendation",
        "",
    ]
    n = 1
    for s in eligible:
        lines.append(
            f"{n}. Use {s['supplier']} first: up to {s['available_units_per_week']:,} units a week of available, "
            f"qualified capacity [CAP-001], with no recorded risk signals [RISK-001]. Capacity is not authorization: "
            f"commitment needs Procurement and Quality approval [CAP-POLICY].")
        n += 1
    fastest = routes[0] if routes else None
    if fastest:
        lines.append(
            f"{n}. Ship on {fastest['name']} first ({fastest['transit_days']}-day transit, cap "
            f"{fastest['max_units_per_week']:,} a week) and put the balance on "
            + ", ".join(f"{r['name']} ({r['transit_days']}-day, cap {r['max_units_per_week']:,})" for r in routes[1:])
            + " [DIST-001]. Allocation changes need Distribution Lead and Quality approval [DIST-POLICY].")
        n += 1
    for s in blocked:
        lines.append(
            f"{n}. Do not commit {s['supplier']} yet. It reports {s['available_units_per_week']:,} units a week "
            f"[CAP-001] but has elevated risk: " + "; ".join(b["reason"] for b in s["blockers"])
            + " [RISK-001, RISK-POLICY]. Escalate to " + " and ".join(s["escalate_to"])
            + f". Keep change packet {plan['packet_review']['packet_id']} on hold [PACKET-001].")
        n += 1
    if residual_weeks:
        lines.append(
            f"{n}. Decide how to handle the remaining {t['residual_gap']:,} units "
            f"(weeks {', '.join(str(w['week']) for w in residual_weeks)}). Eligible capacity covers "
            f"{t['covered']:,} of the {t['gap']:,}-unit gap [DISRUPT-001, CAP-001]. This needs a human decision; "
            "the agent has not chosen an option.")
        n += 1
    cw = plan["contract_watch"]
    lines.append(
        f"{n}. Keep {cw['supplier']} production in standard bottle packaging. "
        f"{' and '.join(cw['requires_written_authorization']).capitalize()} need written authorization from "
        f"{cw['authorization_owner']} first [CONTRACT-AR-001].")
    lines += ["", "## Week-by-week plan", ""]
    header = "| Week | Starts | Gap | " + " | ".join(s["supplier"] for s in eligible) + " | " + \
             " | ".join(route_names) + " | Unrouted | Residual gap |"
    lines += [header, "|" + "---|" * (header.count("|") - 1)]
    for w in plan["weeks"]:
        by_supplier = {a["supplier"]: a["units"] for a in w["supplier_allocations"]}
        lines.append(
            f"| {w['week']} | {w['week_start'] or '-'} | {w['gap']:,} | "
            + " | ".join(f"{by_supplier.get(s['supplier'], 0):,}" for s in eligible) + " | "
            + " | ".join(f"{w['routes'].get(r, 0):,}" for r in route_names)
            + f" | {w['unrouted']:,} | {w['residual_gap']:,} |")
    lines.append(
        f"| **Total** | | **{t['gap']:,}** | "
        + " | ".join(f"**{sum(a['units'] for w in plan['weeks'] for a in w['supplier_allocations'] if a['supplier'] == s['supplier']):,}**"
                     for s in eligible) + " | "
        + " | ".join(f"**{sum(w['routes'].get(r, 0) for w in plan['weeks']):,}**" for r in route_names)
        + f" | **{sum(w['unrouted'] for w in plan['weeks']):,}** | **{t['residual_gap']:,}** |")
    lines += ["", "Sources: gaps [DISRUPT-001], capacity [CAP-001], routes and caps [DIST-001].", ""]

    lines += ["## What changes if Quality clears the blocked supplier", "",
              "A scenario for the decision-makers, not a recommendation."]
    if shortfalls:
        for w in shortfalls:
            lines.append(
                f"- Week {w['week']}: {w['units_to_route']:,} units would need moving, but documented routes carry "
                f"{w['documented_route_capacity']:,} a week [DIST-001]: a {w['route_shortfall']:,}-unit routing shortfall.")
        lines.append("- Route Elm has no assessed values [DIST-001]; Supply Chain Operations owns that gap [DIST-POLICY].")
    else:
        lines.append("- Documented routes could carry the extra volume in every week [DIST-001].")
    lines += ["", "## Supplier assessment", "",
              "| Supplier | Available a week | Qualification | Overdue corrective actions | Risk | Recommend now? |",
              "|---|---|---|---|---|---|"]
    for s in plan["suppliers"]:
        lines.append(
            f"| {s['supplier']} | {s['available_units_per_week']:,} [CAP-001] | {s['qualification']} [CAP-001] | "
            f"{s['overdue_corrective_actions']} [RISK-001] | {s['risk']} [RISK-POLICY] | "
            f"{'Yes' if s['eligible_to_recommend'] else 'No: escalate'} |")
    pr = plan["packet_review"]
    lines += ["", f"## Change packet {pr['packet_id']}", "",
              f"Status: {pr['status']} [PACKET-001]. Completeness review is not approval [PACKET-POLICY].", "",
              "| Missing item | Owner |", "|---|---|"]
    lines += [f"| {m['item']} | {m['owner']} [PACKET-POLICY] |" for m in pr["missing"]]
    lines += ["", "## Human approvals required", "", "| Decision | Approvers | Source |", "|---|---|---|"]
    lines += [f"| {a['decision']} | {', '.join(a['approvers'])} | {', '.join(a['sources'])} |"
              for a in plan["approvals_required"]]
    lines += ["", "## Escalations", ""]
    lines += [f"- {e['item']}. Owner: {', '.join(e['to'])} [{', '.join(e['sources'])}]" for e in plan["escalations"]]
    lines += ["", "## Method", "",
              "- Weekly gap = forecast minus internal capacity, floored at zero (planner demand file), "
              "or the DISRUPT-001 average when no file is supplied.",
              "- Only suppliers with complete qualification and no elevated risk signal are allocated "
              "(RISK-POLICY rubric).",
              "- Volume is routed on the fastest documented route up to its cap, then the next. "
              "Unassessed routes are never used.",
              "- Computed by Caldova's deterministic planning code; the model did not do the arithmetic.",
              "", "No operational action taken.", ""]
    return "\n".join(lines)


def _short_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()[:10]
