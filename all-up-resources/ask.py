"""One caller for all three Caldova agents: invoke by name, same code every time.

  python all-up-resources/ask.py --agent caldova-ops-advisor-hosted "Which supplier and route should we use?"
  python all-up-resources/ask.py --agent caldova-ops-investigator \
      --attach all-up-resources/inputs/aller-demand-plan.csv --download "Build the evidence package"
  python all-up-resources/ask.py --agent caldova-ops-runtime "Plan and submit the response to DISRUPT-001"
  python all-up-resources/ask.py --agent caldova-ops-runtime --continue "Show me the case"

Every request goes through an explicit conversation (the Copilot harness
requires one, and it keeps the trace readable for the other two).

Needs: pip install "azure-ai-projects>=2.9.0" azure-identity, and az login.
The project endpoint comes from FOUNDRY_PROJECT_ENDPOINT, else
AZURE_AI_PROJECT_ENDPOINT, else the active azd environment.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

STATE = Path(__file__).resolve().parent / ".ask-state.json"


def load_dotenv() -> None:
    """Load the nearest .env (this folder or a parent) without overriding variables already set."""
    for folder in Path(__file__).resolve().parents:
        env = folder / ".env"
        if env.is_file():
            for line in env.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    if value.strip():
                        os.environ.setdefault(key.strip(), value.strip().strip('"'))
            return


def project_endpoint() -> str:
    for name in ("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        values = subprocess.run(["azd", "env", "get-values"], capture_output=True, text=True, check=True).stdout
        for line in values.splitlines():
            key, _, value = line.partition("=")
            if key == "AZURE_AI_PROJECT_ENDPOINT":
                return value.strip().strip('"')
    except (OSError, subprocess.CalledProcessError):
        pass
    sys.exit("Set FOUNDRY_PROJECT_ENDPOINT (https://<account>.services.ai.azure.com/api/projects/<project>).")


def file_part(client, path: Path) -> dict:
    """Upload the attachment to Foundry Files; fall back to inline data if upload isn't allowed."""
    try:
        with open(path, "rb") as handle:
            uploaded = client.files.create(file=handle, purpose="assistants")
        print(f"[attached {path.name} as Foundry file {uploaded.id}]")
        return {"type": "input_file", "file_id": uploaded.id}
    except Exception as exc:  # noqa: BLE001 - any upload failure falls back to inline data
        print(f"[upload failed ({type(exc).__name__}); sending {path.name} inline]")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"type": "input_file", "filename": path.name, "file_data": f"data:text/csv;base64,{data}"}


def find_file_ids(node, found=None) -> list:
    found = [] if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "file_id" and isinstance(value, str) and value not in found:
                found.append(value)
            else:
                find_file_ids(value, found)
    elif isinstance(node, list):
        for item in node:
            find_file_ids(item, found)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompt")
    parser.add_argument("--agent", required=True, help="Foundry agent name")
    parser.add_argument("--attach", type=Path, help="file to send with the message (for example the demand plan CSV)")
    parser.add_argument("--conversation", help="continue this conversation ID")
    parser.add_argument("--continue", dest="resume", action="store_true", help="continue the last conversation with this agent")
    parser.add_argument("--download", action="store_true", help="download files the agent returns into ./downloads")
    parser.add_argument("--show-steps", action="store_true", help="print each output item type (tool calls, messages)")
    args = parser.parse_args()
    load_dotenv()

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    project = AIProjectClient(endpoint=project_endpoint(), credential=DefaultAzureCredential(), allow_preview=True)
    client = project.get_openai_client(agent_name=args.agent)   # agent-scoped Responses + conversations
    files = project.get_openai_client()                          # project-scoped Foundry Files

    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    resumed = args.conversation or (state.get(args.agent) if args.resume else None)

    if args.attach:
        content = [{"type": "input_text", "text": args.prompt}, file_part(files, args.attach)]
        request_input = [{"role": "user", "content": content}]
    else:
        request_input = args.prompt

    def attempt(conversation_id):
        response = client.responses.create(conversation=conversation_id, input=request_input)
        # The harness attaches the toolbox with approval on, so approve the read-only
        # caldova_ops calls here (in Canvas or the Portal you click Approve).
        while True:
            if args.show_steps:
                for item in response.output:
                    data = item.model_dump()
                    label = data.get("name") or data.get("server_label") or data.get("role") or ""
                    print(f"  step: {data.get('type')} {label}".rstrip())
            approvals = [i for i in response.output if i.model_dump().get("type") == "mcp_approval_request"]
            if not approvals:
                return response
            response = client.responses.create(
                conversation=conversation_id,
                input=[{"type": "mcp_approval_response", "approval_request_id": a.id, "approve": True} for a in approvals],
            )

    # The harness preview intermittently fails right after the tool approval (status failed with
    # server_error, or HTTP 400 "Unknown approval request IDs"). A fresh conversation normally succeeds.
    tries = 1 if resumed else 3
    for n in range(1, tries + 1):
        conversation_id = resumed or client.conversations.create().id
        state[args.agent] = conversation_id
        STATE.write_text(json.dumps(state, indent=2))
        try:
            response = attempt(conversation_id)
            failed = response.status == "failed" and getattr(getattr(response, "error", None), "code", "") == "server_error"
        except Exception as exc:  # noqa: BLE001
            if "approval request" not in str(exc).lower():
                raise
            response, failed = None, True
        if not failed or n == tries:
            break
        print(f"[transient service error on attempt {n}; retrying in a new conversation]")
    if response is None:
        sys.exit("The service rejected the tool approval on every attempt; try again in a minute.")
    print()
    if getattr(response, "error", None):
        print(f"error: {response.error}")
    print(response.output_text)
    print()
    print(f"agent={args.agent} conversation={conversation_id} response={response.id} status={response.status}")

    file_ids = find_file_ids(response.model_dump())
    for file_id in file_ids:
        print(f"returned file: {file_id}")
        if args.download:
            target = Path("downloads")
            target.mkdir(exist_ok=True)
            try:
                meta = files.files.retrieve(file_id)
                name = Path(getattr(meta, "filename", None) or file_id).name
                (target / name).write_bytes(files.files.content(file_id).read())
                print(f"  saved downloads/{name}")
            except Exception as exc:  # noqa: BLE001
                print(f"  could not download {file_id}: {exc}")


if __name__ == "__main__":
    main()
