"""Demo 3: main.py wiring, checked against stub Agent Framework modules.

This proves the tools, toolbox switch and host start-up are wired correctly.
It does not prove the real agent-framework packages accept them: run
`azd ai agent run` with the real packages for that (see SETUP.md)."""
import asyncio
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from _paths import RUNTIME

CREATED = {}


def _install_stubs():
    af = types.ModuleType("agent_framework")

    def tool(approval_mode=None):
        def wrap(fn):
            fn.approval_mode = approval_mode
            return fn
        return wrap

    class Agent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            CREATED["agent"] = self

    af.tool, af.Agent = tool, Agent

    foundry = types.ModuleType("agent_framework.foundry")

    class FoundryChatClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    foundry.FoundryChatClient = FoundryChatClient
    af.foundry = foundry

    hosting = types.ModuleType("agent_framework_foundry_hosting")

    class ResponsesHostServer:
        def __init__(self, agent):
            CREATED["server_agent"] = agent

        async def run_async(self):
            CREATED["ran"] = True

    class FoundryToolbox:
        def __init__(self, credential):
            self.credential = credential

    hosting.ResponsesHostServer, hosting.FoundryToolbox = ResponsesHostServer, FoundryToolbox

    identity = types.ModuleType("azure.identity")
    identity.DefaultAzureCredential = lambda: "credential"
    pydantic = types.ModuleType("pydantic")

    class BaseModel:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def model_dump(self):
            return dict(self.__dict__)

    pydantic.BaseModel, pydantic.Field = BaseModel, (lambda *a, **k: None)
    stubs = {"agent_framework": af, "agent_framework.foundry": foundry,
             "agent_framework_foundry_hosting": hosting, "azure": types.ModuleType("azure"),
             "azure.identity": identity, "pydantic": pydantic}
    return mock.patch.dict(sys.modules, stubs)


class MainWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {
            "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/p",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-5.4-mini",
            "CALDOVA_CASE_DIR": self.tmp.name, "CALDOVA_CASE_STORE": "file",
            "TOOLBOX_ENDPOINT": "", "TOOLBOX_NAME": ""})
        self.env.start()
        self.stubs = _install_stubs()
        self.stubs.start()
        sys.path.insert(0, str(RUNTIME))
        sys.modules.pop("main", None)
        sys.modules.pop("runtime", None)
        self.main = importlib.import_module("main")

    def tearDown(self):
        sys.path.remove(str(RUNTIME))
        sys.modules.pop("main", None)
        self.stubs.stop()
        self.env.stop()
        self.tmp.cleanup()

    def names(self, agent):
        return [getattr(t, "__name__", type(t).__name__) for t in agent.tools]

    def test_local_evidence_tools_without_toolbox(self):
        agent = self.main.build_agent("cred")
        self.assertEqual(self.names(agent), ["plan_disruption_response", "submit_recommendation", "get_case",
                                             "list_cases", "get_evidence", "list_evidence_sources"])
        self.assertEqual(agent.default_options, {"store": False})
        self.assertEqual(agent.client.kwargs["model"], "gpt-5.4-mini")
        self.assertTrue(all(t.approval_mode == "never_require" for t in agent.tools))

    def test_toolbox_replaces_local_evidence_tools(self):
        os.environ["TOOLBOX_ENDPOINT"] = "https://example/toolboxes/caldova-ops/mcp"
        agent = self.main.build_agent("cred")
        self.assertEqual(self.names(agent)[0], "FoundryToolbox")
        self.assertNotIn("get_evidence", self.names(agent))

    def test_submit_tool_runs_the_gate(self):
        agent = self.main.build_agent("cred")
        tools = {t.__name__: t for t in agent.tools}
        template = json.loads(tools["plan_disruption_response"]())["proposal_template"]
        weeks = [self.main.WeekAllocation(**w) for w in template["weeks"]]
        weeks[0].routes = {"Cedar": 700, "Birch": 400}
        result = json.loads(asyncio.run(tools["submit_recommendation"]("CASE-X", weeks, template["cited_sources"], "test")))
        self.assertEqual(result["status"], "rejected_by_policy_gate")
        case = json.loads(asyncio.run(tools["get_case"]("CASE-X")))
        self.assertEqual(case["case"]["status"], "rejected_by_policy_gate")
        listed = json.loads(asyncio.run(tools["list_cases"]()))
        self.assertEqual(listed["cases"][0]["case_id"], "CASE-X")
        self.assertIn("No case", json.loads(asyncio.run(tools["get_case"]("CASE-NONE")))["error"])
        self.assertIn("could not be read", json.loads(tools["plan_disruption_response"]("week,oops\n1,2"))["error"])

    def test_main_starts_the_responses_host(self):
        CREATED.clear()
        asyncio.run(self.main.main())
        self.assertTrue(CREATED["ran"])
        self.assertIs(CREATED["server_agent"], CREATED["agent"])


if __name__ == "__main__":
    unittest.main()
