"""Demo 2: the skill script the Copilot harness runs in its sandbox."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _paths import DEMAND, ROOT, SKILL

SCRIPT = SKILL / "scripts" / "build_evidence_package.py"
GOLDEN = ROOT / "demo2-equip-harness" / "golden"


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


class SkillTests(unittest.TestCase):
    def test_skill_manifest_follows_agent_skills_rules(self):
        text = (SKILL / "SKILL.md").read_text()
        front = re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1)
        fields = dict(line.split(": ", 1) for line in front.splitlines())
        self.assertRegex(fields["name"], r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
        self.assertNotIn("--", fields["name"])
        self.assertEqual(fields["name"], SKILL.name)
        self.assertFalse(fields["description"].startswith(("'", '"')), "must be unquoted")
        self.assertLessEqual(len(fields["description"]), 1024)
        self.assertIn("get_evidence_bundle", text)
        self.assertIn("scripts/build_evidence_package.py", text)

    def test_builds_package_matching_golden_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run("--bundle", str(GOLDEN / "evidence" / "bundle.json"), "--demand", str(DEMAND), "--out", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["totals"], {"gap": 9000, "covered": 7100, "residual_gap": 1900})
            self.assertEqual(summary["blocked_suppliers"], ["Northbank"])
            for name in ("caldova-evidence-package.md", "allocation-plan.csv", "plan.json"):
                self.assertEqual((Path(tmp) / name).read_text(), (GOLDEN / "out" / name).read_text(),
                                 f"golden/out/{name} is stale: rerun the skill script (see demo2 README)")

    def test_without_demand_file_uses_brief_average(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run("--bundle", str(GOLDEN / "evidence" / "bundle.json"), "--out", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["basis"], "DISRUPT-001 weekly average")

    def test_tampered_or_missing_bundle_fails_with_instructions(self):
        bundle = json.loads((GOLDEN / "evidence" / "bundle.json").read_text())
        bundle["documents"]["CAP-001"]["data"]["suppliers"][1]["qualification"] = "complete"
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bundle.json"
            bad.write_text(json.dumps(bundle))
            result = run("--bundle", str(bad), "--out", tmp)
            self.assertEqual(result.returncode, 2)
            self.assertIn("digest mismatch", result.stderr)
            result = run("--bundle", str(Path(tmp) / "missing.json"), "--out", tmp)
            self.assertEqual(result.returncode, 2)
            self.assertIn("get_evidence_bundle", result.stderr)


if __name__ == "__main__":
    unittest.main()
