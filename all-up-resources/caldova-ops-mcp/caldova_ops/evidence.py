"""Read-only access to the synthetic Caldova evidence register.

Every record carries a source ID (for example ``CAP-001``) so that agents can
cite it, plus a ``data`` block with the same facts in structured form so that
code can compute with them instead of parsing prose.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_PATH = Path(__file__).resolve().parent / "data" / "scenario.json"
# The planner's current weekly demand plan (the attachment used in demo 2).
DEMAND_PLAN_PATH = DATA_PATH.parent / "aller-demand-plan.csv"


class EvidenceError(Exception):
    """Raised when evidence is missing, unknown or has been altered."""


def load_scenario(path: Optional[Path] = None) -> Dict[str, Any]:
    with open(path or DATA_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _documents(scenario: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return (scenario or load_scenario())["documents"]


def list_sources(scenario: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """Source ID, title and owner for every record (no content)."""
    return [
        {"source_id": sid, "title": doc["title"], "owner": doc["owner"]}
        for sid, doc in _documents(scenario).items()
    ]


def get_document(source_id: str, scenario: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    docs = _documents(scenario)
    key = source_id.strip().upper()
    if key not in docs:
        raise EvidenceError(
            f"Unknown source ID '{source_id}'. Known IDs: {', '.join(sorted(docs))}."
        )
    record = copy.deepcopy(docs[key])
    record["source_id"] = key
    return record


def get_documents(source_ids: List[str], scenario: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return [get_document(sid, scenario) for sid in source_ids]


def digest(documents: Dict[str, Any]) -> str:
    """SHA-256 over a canonical JSON form, so formatting changes don't matter
    but any change to a value does."""
    canonical = json.dumps(documents, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_bundle(scenario: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every record in one object, with a digest the packaging script checks."""
    scenario = scenario or load_scenario()
    documents = copy.deepcopy(scenario["documents"])
    return {
        "scenario": scenario["scenario"],
        "version": scenario["version"],
        "provenance": scenario["provenance"],
        "units": scenario["units"],
        "documents": documents,
        "bundle_sha256": digest(documents),
    }


def verify_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Return the bundle's documents if its digest matches, else raise."""
    if not isinstance(bundle, dict) or "documents" not in bundle or "bundle_sha256" not in bundle:
        raise EvidenceError(
            "Evidence bundle is malformed: expected the verbatim JSON returned by the "
            "caldova_ops get_evidence_bundle tool (keys 'documents' and 'bundle_sha256')."
        )
    actual = digest(bundle["documents"])
    if actual != bundle["bundle_sha256"]:
        raise EvidenceError(
            "Evidence bundle digest mismatch: the documents differ from what the trusted "
            "caldova_ops system returned. Fetch the bundle again and save it unmodified."
        )
    return bundle["documents"]
