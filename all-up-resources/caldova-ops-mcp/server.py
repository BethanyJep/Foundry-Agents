"""caldova-ops MCP server (streamable HTTP at /mcp).

Run locally:   pip install -r requirements.txt && python server.py
Deploy:        ./deploy.sh   (Azure Container Apps)
Then register it once as the caldova-ops toolbox (see azure.yaml at the repo root).

If CALDOVA_OPS_MCP_KEY is set, every request must send it in the
x-caldova-key header. The Foundry project connection holds the key, so agents
never see it.
"""
from __future__ import annotations

import hmac
import json
import os

from mcp.server.fastmcp import FastMCP

from tools import ALL_TOOLS

KEY_HEADER = b"x-caldova-key"


class RequireKey:
    """Minimal ASGI middleware: reject HTTP requests without the shared key."""

    def __init__(self, app, key: str | None):
        self.app = app
        self.key = key.encode("utf-8") if key else None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/healthz":
            await _respond(send, 200, {"status": "ok"})
            return
        if self.key is not None and scope["type"] == "http":
            supplied = dict(scope.get("headers") or []).get(KEY_HEADER, b"")
            if not hmac.compare_digest(supplied, self.key):
                await _respond(send, 401, {"error": "missing or invalid x-caldova-key"})
                return
        await self.app(scope, receive, send)


async def _respond(send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(payload)).encode())]})
    await send({"type": "http.response.body", "body": payload})


def build_app():
    # host="0.0.0.0" so the SDK doesn't apply localhost-only Host checks behind Container Apps ingress.
    mcp = FastMCP("caldova-ops", host="0.0.0.0", stateless_http=True, json_response=True)
    for fn in ALL_TOOLS:
        mcp.tool()(fn)
    return RequireKey(mcp.streamable_http_app(), os.environ.get("CALDOVA_OPS_MCP_KEY"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
