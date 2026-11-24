import copy
import unittest

import _paths  # noqa: F401
from caldova_ops import (build_plan, load_scenario, proposal_from_plan, read_demand_plan,
                         render_csv, render_markdown, validate_proposal)
from _paths import DEMAND


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = load_scenario()["documents"]
        cls.rows = read_demand_plan(DEMAND)
        cls.plan = build_plan(cls.docs, cls.rows)

    def test_weekly_gaps_from_demand_file(self):
        self.assertEqual([r["gap"] for r in self.rows], [1100, 1400, 1800, 1700, 1500, 1500])
        self.assertEqual(sum(r["gap"] for r in self.rows), 9000)  # matches DISRUPT-001 total

    def test_only_qualified_low_risk_supplier_is_allocated(self):
        suppliers = {a["supplier"] for w in self.plan["weeks"] for a in w["supplier_allocations"]}
        self.assertEqual(suppliers, {"Aster Ridge"})
        northbank = next(s for s in self.plan["suppliers"] if s["supplier"] == "Northbank")
        self.assertFalse(northbank["eligible_to_recommend"])
        self.assertEqual(northbank["risk"], "elevated")
        self.assertEqual(northbank["escalate_to"], ["Supplier Assurance", "Quality"])

    def test_totals_and_residual(self):
        self.assertEqual(self.plan["totals"], {"gap": 9000, "covered": 7100, "residual_gap": 1900})
        self.assertEqual([w["residual_gap"] for w in self.plan["weeks"]], [0, 200, 600, 500, 300, 300])

    def test_fastest_route_first_within_caps(self):
        self.assertEqual(self.plan["weeks"][0]["routes"], {"Cedar": 600, "Birch": 500})
        for w in self.plan["weeks"][1:]:
            self.assertEqual(w["routes"], {"Cedar": 600, "Birch": 600})
            self.assertEqual(w["unrouted"], 0)

    def test_what_if_shows_route_constraint(self):
        shortfalls = {w["week"]: w["route_shortfall"] for w in self.plan["what_if_blocked_suppliers_cleared"]}
        self.assertEqual(shortfalls, {1: 0, 2: 0, 3: 200, 4: 100, 5: 0, 6: 0})

    def test_flat_average_when_no_file(self):
        flat = build_plan(self.docs)
        self.assertEqual(flat["basis"], "DISRUPT-001 weekly average")
        self.assertEqual(flat["totals"], {"gap": 9000, "covered": 7200, "residual_gap": 1800})

    def test_packet_review_names_every_owner(self):
        owners = {m["item"]: m["owner"] for m in self.plan["packet_review"]["missing"]}
        self.assertEqual(owners, {"qualification evidence": "Quality", "Procurement signature": "Procurement",
                                  "Quality signature": "Quality", "rollback plan": "Change owner"})

    def test_renderers_cite_and_never_claim_action(self):
        md = render_markdown(self.plan)
        for sid in ("DISRUPT-001", "CAP-001", "CAP-POLICY", "DIST-001", "DIST-POLICY", "RISK-001",
                    "RISK-POLICY", "PACKET-001", "PACKET-POLICY", "CONTRACT-AR-001"):
            self.assertIn(sid, md)
        self.assertIn("No operational action taken.", md)
        self.assertNotIn("approved.", md.lower())
        csv_text = render_csv(self.plan)
        self.assertEqual(len(csv_text.strip().splitlines()), 7)


class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = load_scenario()["documents"]
        cls.rows = read_demand_plan(DEMAND)
        cls.good = proposal_from_plan(build_plan(cls.docs, cls.rows), "CASE-T")

    def check(self, proposal):
        return validate_proposal(self.docs, proposal, self.rows)

    def test_compliant_plan_is_pending_not_approved(self):
        result = self.check(self.good)
        self.assertTrue(result["accepted"], result["violations"])
        self.assertEqual(result["status"], "pending_human_approval")
        approvers = {a["decision"]: a["approvers"] for a in result["required_approvals"]}
        self.assertEqual(approvers["Change route allocations"], ["Distribution Lead", "Quality"])
        self.assertEqual(result["open_gap_by_week"], {2: 200, 3: 600, 4: 500, 5: 300, 6: 300})

    def test_700_on_cedar_is_rejected(self):
        bad = copy.deepcopy(self.good)
        bad["weeks"][0]["routes"] = {"Cedar": 700, "Birch": 400}
        result = self.check(bad)
        self.assertEqual(result["status"], "rejected_by_policy_gate")
        self.assertIn("exceeds its maximum allocation of 600", result["violations"][0]["violation"])
        self.assertEqual(result["violations"][0]["sources"], ["DIST-001"])

    def test_northbank_and_unassessed_route_are_rejected(self):
        bad = copy.deepcopy(self.good)
        bad["weeks"].append({"week": 3, "supplier": "Northbank", "units": 600, "routes": {"Elm": 600}})
        messages = " ".join(v["violation"] for v in self.check(bad)["violations"])
        self.assertIn("Northbank cannot be committed", messages)
        self.assertIn("Route Elm has not been assessed", messages)

    def test_over_capacity_overcommit_unrouted_and_uncited(self):
        bad = {"weeks": [{"week": 1, "supplier": "Aster Ridge", "units": 1300, "routes": {"Cedar": 600}}],
               "cited_sources": ["CAP-001"]}
        messages = " ".join(v["violation"] for v in self.check(bad)["violations"])
        self.assertIn("exceeds available 1200", messages)
        self.assertIn("documented gap is 1100", messages)
        self.assertIn("1300 units committed but 600 routed", messages)
        self.assertIn("must cite DISRUPT-001", messages)

    def test_unknown_supplier_and_week(self):
        bad = {"weeks": [{"week": 9, "supplier": "Aster Ridge", "units": 10, "routes": {"Cedar": 10}},
                         {"week": 1, "supplier": "Acme", "units": 10, "routes": {"Cedar": 10}}],
               "cited_sources": list(self.good["cited_sources"])}
        messages = " ".join(v["violation"] for v in self.check(bad)["violations"])
        self.assertIn("outside the disruption window", messages)
        self.assertIn("'Acme' is not in the capacity register", messages)


if __name__ == "__main__":
    unittest.main()
