"""Caldova operations evidence and planning (synthetic training scenario).

Canonical copy. `python all-up-resources/sync_shared.py` vendors this package into the
MCP server, the harness skill and the hosted agent; tests fail if a copy drifts.
"""
from .evidence import (  # noqa: F401
    DATA_PATH, DEMAND_PLAN_PATH, EvidenceError, evidence_bundle, get_document, get_documents,
    list_sources, load_scenario, verify_bundle,
)
from .planning import (  # noqa: F401
    REQUIRED_CITATIONS, PlanningError, build_plan, proposal_from_plan,
    read_demand_plan, render_csv, render_markdown, validate_proposal,
)
