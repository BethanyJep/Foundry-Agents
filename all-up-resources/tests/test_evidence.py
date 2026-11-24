"""The structured data must say exactly what the prose says, so a model reading
the text and code reading the data can never disagree."""
import json
import re
import unittest

import _paths  # noqa: F401
from caldova_ops import EvidenceError, evidence_bundle, get_document, load_scenario, verify_bundle
from _paths import ROOT


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.docs = load_scenario()["documents"]

    def test_every_record_has_owner_title_text(self):
        for sid, doc in self.docs.items():
            self.assertTrue(re.match(r"^[A-Z]+(-[A-Z0-9]+)+$", sid), sid)
            for key in ("owner", "title", "text", "data"):
                self.assertIn(key, doc, f"{sid} missing {key}")

    def test_numbers_in_data_appear_in_text(self):
        def numbers(obj):
            if isinstance(obj, bool):
                return []
            if isinstance(obj, int):
                return [obj]
            if isinstance(obj, dict):
                return [n for v in obj.values() for n in numbers(v)]
            if isinstance(obj, list):
                return [n for v in obj for n in numbers(v)]
            return []
        for sid, doc in self.docs.items():
            text_numbers = {int(n) for n in re.findall(r"\d+", doc["text"].replace(",", ""))}
            words = {"two": 2}
            text_numbers |= {v for k, v in words.items() if k in doc["text"].lower()}
            for n in numbers(doc["data"]):
                if n == 0:
                    continue
                self.assertIn(n, text_numbers, f"{sid}: data value {n} is not in the text")

    def test_fixture_text_is_stable(self):
        # Key fixture texts the demos and docs quote must stay identical.
        self.assertTrue(self.docs["DIST-001"]["text"].startswith("Synthetic route register v1.0: Cedar has a 2-day transit"))
        self.assertIn("Northbank reports 1800 training units per week", self.docs["CAP-001"]["text"])

    def test_bundle_digest_detects_tampering(self):
        bundle = json.loads(json.dumps(evidence_bundle()))
        self.assertEqual(set(verify_bundle(bundle)), set(self.docs))
        bundle["documents"]["DIST-001"]["data"]["routes"][0]["max_units_per_week"] = 700
        with self.assertRaises(EvidenceError):
            verify_bundle(bundle)

    def test_pretty_printing_does_not_break_digest(self):
        bundle = evidence_bundle()
        reformatted = json.loads(json.dumps(bundle, indent=4, sort_keys=False))
        verify_bundle(reformatted)

    def test_unknown_source(self):
        with self.assertRaises(EvidenceError):
            get_document("NOPE-1")
        self.assertEqual(get_document("cap-001")["source_id"], "CAP-001")


class SyncTests(unittest.TestCase):
    def test_vendored_copies_match(self):
        import subprocess, sys
        result = subprocess.run([sys.executable, str(ROOT / "all-up-resources" / "sync_shared.py"), "--check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
