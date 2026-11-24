"""Caldova Ops Runtime: live web demo for the hosted agent (demo 3).

Serves a single-page UI and a small JSON API in front of the DEPLOYED hosted agent
(caldova-ops-runtime). Chat goes to the agent through the Foundry project endpoint, the same call
path as all-up-resources/ask.py; the case panel mirrors what the agent's own tools return from the
Foundry state store. The policy-gate console runs Caldova's real gate (runtime.validate_proposal)
as a dry run and never writes.

Needs: pip install "azure-ai-projects>=2.9.0" azure-identity, az login, and the project endpoint
in the root .env (or the active azd environment).

  python demo3-run-hosted/web-demo/server.py            # http://127.0.0.1:8787
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
RUNTIME_DIR = HERE.parent / "src" / "caldova-ops-runtime"
STATIC = HERE / "static"


def fresh_case_id() -> str:
    """A new case per demo run, so the shared state store's older cases never leak onto the stage."""
    return time.strftime("CASE-DEMO-%m%d-%H%M%S")


AGENT_NAME = "caldova-ops-runtime"
MAX_BODY = 256 * 1024

sys.path.insert(0, str(RUNTIME_DIR))
import runtime  # noqa: E402  (the hosted agent's own module)

LOCK = threading.Lock()


class AppState:
    def __init__(self):
        self.client = None
        self.conversations: Dict[str, str] = {}        # UI session -> Foundry conversation ID
        self.observed: Dict[str, Dict[str, Any]] = {}  # cases seen in the agent's tool outputs
        self.case_id = fresh_case_id()

    def new_case(self) -> str:
        self.case_id = fresh_case_id()
        self.observed.clear()
        self.conversations.clear()
        return self.case_id

    def agent_client(self):
        """One agent-scoped Responses client for the whole server (created on first use)."""
        if self.client is None:
            try:
                from azure.ai.projects import AIProjectClient
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:
                raise RuntimeError('Needs: pip install "azure-ai-projects>=2.9.0" azure-identity, then az login.') from exc
            sys.path.insert(0, str(HERE.parents[1] / "all-up-resources"))
            import ask
            ask.load_dotenv()
            project = AIProjectClient(endpoint=ask.project_endpoint(), credential=DefaultAzureCredential(), allow_preview=True)
            self.client = project.get_openai_client(agent_name=AGENT_NAME)
        return self.client


# --------------------------------------------------------------------------- agent calls

def chat(state: AppState, session: str, message: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Send one message to the deployed hosted agent. Mirrors all-up-resources/ask.py."""
    client = state.agent_client()
    conversation = state.conversations.get(session) or client.conversations.create().id
    state.conversations[session] = conversation

    started = time.perf_counter()
    response = client.responses.create(conversation=conversation, input=message)
    elapsed = round((time.perf_counter() - started) * 1000)
    steps: List[Dict[str, Any]] = []
    calls: Dict[str, Dict[str, Any]] = {}
    for item in response.output:
        data = item.model_dump()
        kind = data.get("type")
        if kind in ("function_call", "mcp_call"):
            step = {"tool": data.get("name"), "args": _json_or_raw(data.get("arguments")),
                    "result": _json_or_raw(data.get("output")), "ms": None}
            calls[data.get("call_id") or data.get("id")] = step
            steps.append(step)
        elif kind == "function_call_output" and data.get("call_id") in calls:
            calls[data["call_id"]]["result"] = _json_or_raw(data.get("output"))
    for step in steps:
        _observe(state, step)
    return {"text": response.output_text, "total_ms": elapsed}, steps


def _json_or_raw(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _observe(state: AppState, step: Dict[str, Any]) -> None:
    """Keep the case panel in step with what the hosted agent's own tools returned."""
    result = step.get("result")
    if not isinstance(result, dict):
        return
    case = result.get("case")
    if isinstance(case, dict) and case.get("case_id"):
        state.observed[case["case_id"]] = case
    elif step.get("tool") == "submit_recommendation" and result.get("recorded"):
        case = state.observed.setdefault(result["case_id"], {"case_id": result["case_id"], "history": []})
        if not any(h["operation_id"] == result["operation_id"] for h in case["history"]):
            case["history"].append({
                "operation_id": result["operation_id"],
                "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                "status": result["status"], "violations": result["violations"],
                "required_approvals": result["required_approvals"], "open_gap_by_week": result["open_gap_by_week"],
                "proposal": step.get("args") or {},
            })
        case.update(status=result["status"], submissions=len(case["history"]))


# --------------------------------------------------------------------------- API

def api_state(state: AppState) -> Dict[str, Any]:
    plan = runtime.plan_disruption_response()
    docs = runtime.documents()
    return {
        "agent": AGENT_NAME,
        "storage": "Foundry state store",
        "default_case": state.case_id,
        "cases": [c for c in state.observed.values() if c.get("case_id") == state.case_id],
        "plan": {"plan_id": plan["plan_id"], "totals": plan["totals"], "weeks": plan["weeks"],
                 "template": plan["proposal_template"], "blocked_suppliers": plan["blocked_suppliers"],
                 "packet_review": plan["packet_review"]},
        "scenario": {"routes": docs["DIST-001"]["data"]["routes"], "suppliers": docs["CAP-001"]["data"]["suppliers"],
                     "required_citations": list(runtime.REQUIRED_CITATIONS)},
    }


def clean_weeks(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > 60:
        raise ValueError("weeks must be a list of week entries.")
    weeks = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Each week entry must be an object.")
        routes = entry.get("routes") or {}
        if not isinstance(routes, dict):
            raise ValueError("routes must be an object of route name to units.")
        weeks.append({"week": int(entry["week"]), "supplier": str(entry.get("supplier", "")),
                      "units": int(entry["units"]), "routes": {str(k): int(v) for k, v in routes.items()}})
    return weeks


def handle_post(state: AppState, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    if path == "/api/chat":
        message = str(body.get("message", "")).strip()[:2000]
        if not message:
            raise ValueError("Say something first.")
        result, steps = chat(state, str(body.get("session", "ui")), message)
        return {"reply": result, "steps": steps}

    if path == "/api/new-case":
        return {"case_id": state.new_case()}

    if path == "/api/new-conversation":
        state.conversations.pop(str(body.get("session", "ui")), None)
        return {"ok": True}

    if path == "/api/propose":
        # The case file lives in the hosted agent's Foundry state store: check only, never write from here.
        weeks = clean_weeks(body.get("weeks"))
        proposal = {"case_id": str(body.get("case_id") or state.case_id), "weeks": weeks,
                    "cited_sources": [str(c) for c in (body.get("cited_sources") or [])][:30]}
        started = time.perf_counter()
        verdict = runtime.validate_proposal(runtime.documents(), proposal, runtime.current_demand_plan())
        step = {"tool": "validate_proposal", "args": {"proposal": proposal}, "result": verdict,
                "ms": round((time.perf_counter() - started) * 1000)}
        return {"result": {**verdict, "case_id": proposal["case_id"], "dry_run": True}, "steps": [step]}

    raise KeyError(path)


class Handler(BaseHTTPRequestHandler):
    state: AppState

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: int, obj: Any) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            return self._json(200, api_state(self.state))
        if path == "/healthz":
            return self._json(200, {"status": "ok"})
        target = (STATIC / ("index.html" if path in ("", "/") else path.lstrip("/"))).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or "javascript" in ctype:
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_POST(self):
        path = urlparse(self.path).path
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self._json(403, {"error": "cross-origin request refused"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "request too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("JSON object expected.")
            with LOCK:
                return self._json(200, handle_post(self.state, path, body))
        except KeyError:
            return self._json(404, {"error": "not found"})
        except (ValueError, TypeError) as exc:
            return self._json(400, {"error": str(exc) or "bad request"})
        except Exception as exc:  # noqa: BLE001 - show the presenter what went wrong instead of a blank UI
            return self._json(502, {"error": f"{type(exc).__name__}: {exc}"})


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"state": AppState()})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8787)))
    args = parser.parse_args()
    server = make_server(args.host, args.port)
    print(f"Caldova Ops Runtime live demo (agent {AGENT_NAME}): http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
