"""The caldova-ops MCP server: read-only tools and the shared-key check.
The real `mcp` package isn't needed: a stub records what server.py registers."""
import asyncio
import importlib
import sys
import types
import unittest

from _paths import MCP

REGISTERED = []
FASTMCP_KWARGS = {}


class _FakeFastMCP:
    def __init__(self, name, **kwargs):
        FASTMCP_KWARGS.update(kwargs, name=name)

    def tool(self):
        def register(fn):
            REGISTERED.append(fn.__name__)
            return fn
        return register

    def streamable_http_app(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"mcp"})
        return app


def _load_server():
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    fastmcp.FastMCP = _FakeFastMCP
    sys.modules.setdefault("mcp", types.ModuleType("mcp"))
    sys.modules.setdefault("mcp.server", types.ModuleType("mcp.server"))
    sys.modules["mcp.server.fastmcp"] = fastmcp
    sys.path.insert(0, str(MCP))
    try:
        return importlib.import_module("server"), importlib.import_module("tools")
    finally:
        sys.path.remove(str(MCP))


server, tools = _load_server()


def call(app, path="/mcp", headers=()):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    asyncio.run(app({"type": "http", "path": path, "headers": list(headers)}, receive, send))
    return sent[0]["status"]


class McpServerTests(unittest.TestCase):
    def test_registers_all_read_only_tools(self):
        REGISTERED.clear()
        server.build_app()
        self.assertEqual(REGISTERED, [fn.__name__ for fn in tools.ALL_TOOLS])
        self.assertEqual(FASTMCP_KWARGS["host"], "0.0.0.0")
        self.assertTrue(FASTMCP_KWARGS["stateless_http"])
        for name in REGISTERED:
            self.assertFalse(any(verb in name for verb in ("book", "approve", "sign", "block", "update", "set_")), name)

    def test_tools_return_cited_documents(self):
        self.assertEqual([d["source_id"] for d in tools.get_route_register()["documents"]], ["DIST-001", "DIST-POLICY"])
        risk = tools.get_supplier_risk("northbank")
        self.assertEqual(risk["requested_supplier_observation"]["overdue_corrective_actions"], 2)
        self.assertIn("not proof of no risk", tools.get_supplier_risk("Acme")["note"])
        self.assertEqual(tools.get_change_packet("cp-104")["documents"][0]["source_id"], "PACKET-001")
        self.assertEqual(tools.get_supplier_contract("Northbank")["documents"], [])
        self.assertEqual(len(tools.get_evidence_bundle()["bundle_sha256"]), 64)

    def test_key_required_when_configured(self):
        app = server.RequireKey(_FakeFastMCP("x").streamable_http_app(), "s3cret")
        self.assertEqual(call(app), 401)
        self.assertEqual(call(app, headers=[(b"x-caldova-key", b"wrong")]), 401)
        self.assertEqual(call(app, headers=[(b"x-caldova-key", b"s3cret")]), 200)
        self.assertEqual(call(app, path="/healthz"), 200)

    def test_open_when_no_key(self):
        app = server.RequireKey(_FakeFastMCP("x").streamable_http_app(), None)
        self.assertEqual(call(app), 200)


if __name__ == "__main__":
    unittest.main()
