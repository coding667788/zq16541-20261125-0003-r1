import unittest

from proofmarket.buy import buy_best
from proofmarket.check import check_solution
from proofmarket.judge import judge_case
from proofmarket.loader import load_evidence


def case_with_control(**control_overrides):
    control = {
        "id": "C1",
        "required_intervals": [[0, 10]],
        "required_regions": ["CN"],
        "rule": {"id": "one", "kinds": ["annual_report"]},
    }
    control.update(control_overrides)
    return {"case_id": "semantic", "controls": [control], "actions": []}


class SemanticEdgeTests(unittest.TestCase):
    def test_approved_region_intersection_blocks_quote_scope(self):
        case = case_with_control()
        nodes = load_evidence(
            {
                "nodes": [
                    {
                        "id": "E1",
                        "kind": "annual_report",
                        "approved_regions": ["US"],
                        "coverage": [
                            {
                                "controls": ["C1"],
                                "regions": ["*"],
                                "intervals": [[0, 10]],
                            }
                        ],
                    }
                ]
            }
        )
        result = judge_case(case, nodes)
        control = result["controls"][0]
        self.assertFalse(control["proven"])
        self.assertEqual(control["covered_union"], [])
        self.assertEqual(control["actual_valid_evidence_union"], [])

    def test_future_known_at_evidence_is_not_knowable(self):
        case = case_with_control()
        case["decision_time"] = 5
        nodes = load_evidence(
            {
                "nodes": [
                    {
                        "id": "E_FUTURE",
                        "kind": "annual_report",
                        "known_at": 9,
                        "coverage": [{"controls": ["C1"], "intervals": [[0, 10]]}],
                    }
                ]
            }
        )
        result = judge_case(case, nodes)
        dep = result["controls"][0]["first_unprovable_dependency"]
        self.assertEqual(dep["reason"], "not_knowable_at_decision_time")

    def test_composite_covers_nothing_when_prerequisite_invalid(self):
        case = case_with_control(
            rule={"id": "commitment", "kinds": ["vendor_commitment"]}
        )
        nodes = load_evidence(
            {
                "nodes": [
                    {
                        "id": "E_COMP",
                        "kind": "vendor_commitment",
                        "type": "composite",
                        "prerequisites": ["E_MISSING"],
                        "coverage": [{"controls": ["C1"], "intervals": [[0, 10]]}],
                    }
                ]
            }
        )
        result = judge_case(case, nodes)
        self.assertFalse(result["proven"])
        dep = result["first_unprovable_dependency"]
        self.assertEqual(dep["dependency_path"], ["E_COMP", "E_MISSING"])

    def test_false_independence_claim_fails_even_when_actions_are_optimal(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        case = root / "fixtures" / "04_trap_beta" / "case.json"
        evidence = root / "fixtures" / "04_trap_beta" / "evidence.json"
        solution = root / "fixtures" / "04_trap_beta" / "solution-false-claim-good-actions.json"
        report = check_solution(case, evidence, solution)
        self.assertTrue(report["candidate_proven"])
        self.assertFalse(report["ok"])
        self.assertEqual([v["code"] for v in report["violations"]], ["FALSE_INDEPENDENCE"])

    def test_evidence_cycle_cannot_self_prove(self):
        case = case_with_control(rule={"id": "commitment", "kinds": ["commitment"]})
        nodes = load_evidence(
            {
                "nodes": [
                    {"id": "A", "kind": "commitment", "type": "composite", "prerequisites": ["B"]},
                    {"id": "B", "kind": "commitment", "type": "composite", "prerequisites": ["A"]},
                ]
            }
        )
        dep = judge_case(case, nodes)["first_unprovable_dependency"]
        self.assertIn("cycle", dep["reason"])
        self.assertEqual(dep["dependency_path"], ["A", "B", "A"])

    def test_no_feasible_plan_is_reported(self):
        case = {
            "case_id": "impossible",
            "controls": [
                {
                    "id": "C1",
                    "required_intervals": [[0, 1]],
                    "rule": {"kinds": ["annual_report"]},
                }
            ],
            "actions": [{"id": "a1", "grants": ["E1"], "cost": 1}],
        }
        plan = buy_best(case, {})
        self.assertFalse(plan["feasible"])
        self.assertIn("no subset", plan["reason"])


if __name__ == "__main__":
    unittest.main()
