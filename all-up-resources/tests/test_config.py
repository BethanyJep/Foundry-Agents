"""azure.yaml and agent definitions: references resolve, values match the docs."""
import re
import unittest

import yaml

from _paths import ROOT


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dirs = {}
        cls.services = {}
        for f in sorted(ROOT.glob("demo*/*/*/azure.yaml")):
            cfg = yaml.safe_load(f.read_text())
            for name, svc in cfg["services"].items():
                cls.services.setdefault(name, svc)
                cls.dirs.setdefault(name, f.parent)

    def by_host(self, host):
        return {k: v for k, v in self.services.items() if v["host"] == host}

    def test_every_reference_resolves(self):
        for name, svc in self.services.items():
            for ref in svc.get("uses", []):
                self.assertIn(ref, self.services, f"{name} uses unknown {ref}")
            for ref in svc.get("toolboxes", []):
                self.assertEqual(self.services[ref]["host"], "azure.ai.toolbox")
                self.assertIn(ref, svc["uses"], f"{name} must also list {ref} in uses")
            for ref in svc.get("skills", []):
                ref = ref["name"] if isinstance(ref, dict) else ref
                self.assertEqual(self.services[ref]["host"], "azure.ai.skill")
                self.assertIn(ref, svc["uses"], f"{name} must also list {ref} in uses")

    def test_one_toolbox_serves_every_agent(self):
        hosted, prompt, investigator, runtime = (self.services[n] for n in
                                                 ("caldova-ops-advisor-hosted", "caldova-ops-advisor-prompt",
                                                  "caldova-ops-investigator", "caldova-ops-runtime"))
        self.assertEqual(prompt["tools"][0]["server_label"], "caldova_ops")   # same MCP server, attached directly
        self.assertEqual(investigator["toolboxes"], ["caldova-ops"])
        for hosted_agent in (hosted, runtime):
            self.assertIn("caldova-ops", hosted_agent["uses"])
            self.assertEqual(hosted_agent["env"]["TOOLBOX_ENDPOINT"], "${TOOLBOX_CALDOVA_OPS_MCP_ENDPOINT}")
        tool = self.services["caldova-ops"]["tools"][0]
        self.assertEqual(tool["connection"], "caldova-ops-conn")
        self.assertNotIn("KEY", str(hosted) + str(prompt) + str(investigator) + str(runtime))

    def test_harness_agent_matches_learn_values(self):
        inv = self.services["caldova-ops-investigator"]
        self.assertEqual(inv["kind"], "prompt")
        self.assertEqual(inv["harness"], {"type": "microsoft_copilot_preview"})
        toolsets = [t for t in inv["tools"] if t["type"] == "microsoft_copilot_toolset_preview"]
        self.assertEqual(len(toolsets), 1)
        valid = {"filesystem_read", "filesystem_write", "shell", "web", "subagents"}
        self.assertTrue({c["name"] for c in toolsets[0]["configs"]} <= valid)

    def test_demo1_is_a_hosted_agent_with_the_project_guardrail(self):
        # Demo 1: Canvas builds a hosted agent, equips it (toolbox, guardrail) and deploys it.
        adv = self.services["caldova-ops-advisor-hosted"]
        self.assertEqual(adv["kind"], "hosted")
        self.assertTrue((self.dirs["caldova-ops-advisor-hosted"] / adv["project"] / adv["codeConfiguration"]["entryPoint"]).exists())
        self.assertEqual([p["type"] for p in adv["policies"]], ["rai_policy"])
        self.assertEqual(adv["protocols"], [{"protocol": "responses", "version": "2.0.0"}])
        self.assertNotIn("skills", adv)

    def test_demo2_before_is_a_plain_prompt_agent_after_adds_the_harness(self):
        before = self.services["caldova-ops-advisor-prompt"]
        after = self.services["caldova-ops-investigator"]
        self.assertEqual(before["kind"], "prompt")
        self.assertNotIn("harness", before)           # default prompt-agent runtime
        self.assertEqual([t["type"] for t in before["tools"]], ["mcp"])
        self.assertEqual(before.get("skills", []), [])
        self.assertEqual(after["harness"], {"type": "microsoft_copilot_preview"})
        self.assertNotEqual(before["name"], after["name"])   # the harness can't be added to an existing agent
        toolset = [t for t in after["tools"] if t["type"] == "microsoft_copilot_toolset_preview"][0]
        off = {c["name"] for c in toolset["configs"] if c["enabled"] is False}
        self.assertEqual(off, {"web"})  # shell, files and subagents stay on; web stays off (least privilege)
        self.assertEqual([x["name"] for x in after["skills"]], ["caldova-evidence-package"])

    def test_skill_archive_has_manifest_named_like_the_service(self):
        for name, svc in self.by_host("azure.ai.skill").items():
            manifest = (self.dirs[name] / svc["archive"] / "SKILL.md").read_text()
            self.assertRegex(manifest, rf"(?m)^name: {re.escape(name)}$")

    def test_hosted_agent_project(self):
        rt = self.services["caldova-ops-runtime"]
        self.assertEqual(rt["kind"], "hosted")
        self.assertTrue((self.dirs["caldova-ops-runtime"] / rt["project"] / rt["codeConfiguration"]["entryPoint"]).exists())
        self.assertEqual(rt["protocols"], [{"protocol": "responses", "version": "2.0.0"}])
        self.assertIn((rt["container"]["resources"]["cpu"], rt["container"]["resources"]["memory"]),
                      {("0.5", "1Gi"), ("1", "2Gi"), ("2", "4Gi")})

    def test_routine_targets_the_hosted_agent_and_starts_disabled(self):
        routine = self.services["caldova-morning-sweep"]
        self.assertEqual(routine["action"]["agentName"], self.services["caldova-ops-runtime"]["name"])
        self.assertEqual(routine["triggers"]["default"]["type"], "schedule")
        self.assertFalse(routine["enabled"])

    def test_prompt_instructions_match_the_files_on_stage(self):
        advisor = (ROOT / "demo1-build-canvas" / "agent-instructions.txt").read_text().strip()
        self.assertEqual(self.services["caldova-ops-advisor-prompt"]["instructions"], advisor)
        hosted_main = (ROOT / "demo1-build-canvas" / "src" / "caldova-ops-advisor-hosted" / "main.py").read_text()
        self.assertIn(advisor, hosted_main)   # demo 1's hosted agent carries the same instructions
        investigator = (ROOT / "demo2-equip-harness" / "agent-instructions.txt").read_text().strip()
        self.assertEqual(self.services["caldova-ops-investigator"]["instructions"], investigator)
        # "Same instructions": the harness agent adds exactly one line about the skill.
        advisor = self.services["caldova-ops-advisor-prompt"]["instructions"]
        self.assertTrue(investigator.startswith(advisor))
        self.assertEqual(investigator[len(advisor):].strip().count("\n"), 0)

    def test_dependencies_listed_twice_agree(self):
        rt = ROOT / "demo3-run-hosted" / "src" / "caldova-ops-runtime"
        pyproject = re.findall(r'"([^"]+)"', (rt / "pyproject.toml").read_text().split("dependencies = [", 1)[1].split("]")[0])
        requirements = [l.strip() for l in (rt / "requirements.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
        self.assertEqual(pyproject, requirements)


if __name__ == "__main__":
    unittest.main()
