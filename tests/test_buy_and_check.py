import copy
import itertools
import time
import unittest
from pathlib import Path

from proofmarket.buy import buy_best, price_selection
from proofmarket.check import check_solution
from proofmarket.feasibility import FeasibilityBitset
from proofmarket.judge import JudgeEngine
from proofmarket.loader import load_case, load_evidence

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


def load_fixture(name: str):
    return load_case(FIX / name / "case.json"), load_evidence(FIX / name / "evidence.json")


class BuyAndCheckTests(unittest.TestCase):
    def test_alpha_cheap_legal_split_loses_payments_threshold(self):
        case, evidence = load_fixture("03_trap_alpha")
        plan = buy_best(case, evidence, include_judgement=False)
        self.assertTrue(plan["feasible"])
        self.assertEqual(
            plan["selected_actions"],
            ["act_p_a1_cheap", "act_p_b_fast"],
        )
        self.assertEqual(plan["metrics"]["full_period_cost"], 4)
        self.assertEqual(plan["metrics"]["review_days"], 2)

        bad = (FIX / "03_trap_alpha" / "solution-bad-review.json")
        report = check_solution(case, evidence, bad)
        self.assertFalse(report["ok"])
        codes = [v["code"] for v in report["violations"]]
        self.assertIn("REVIEW_DAYS_NOT_MINIMAL", codes)
        violation = next(v for v in report["violations"] if v["code"] == "REVIEW_DAYS_NOT_MINIMAL")
        self.assertEqual(violation["candidate_review_days"], 6)
        self.assertEqual(violation["optimal_review_days"], 2)

        good = FIX / "03_trap_alpha" / "solution-good.json"
        self.assertTrue(check_solution(case, evidence, good)["ok"])

    def test_beta_distinct_upstreams_are_rejected_as_independent(self):
        case, evidence = load_fixture("04_trap_beta")
        plan = buy_best(case, evidence, include_judgement=False)
        self.assertEqual(
            plan["selected_actions"],
            ["act_q_lab_r", "act_q_lab_s"],
        )
        self.assertEqual(plan["metrics"]["full_period_cost"], 4)
        report = check_solution(
            case, evidence, FIX / "04_trap_beta" / "solution-false-upstreams.json"
        )
        self.assertFalse(report["ok"])
        false_claim = next(v for v in report["violations"] if v["code"] == "FALSE_INDEPENDENCE")
        claim_codes = [x["code"] for x in false_claim["claim_violations"]]
        self.assertIn("UPSTREAM_SOURCES_NOT_INDEPENDENT", claim_codes)
        self.assertIn("COMMON_OWNERSHIP", claim_codes)
        self.assertIn("INFEASIBLE_SOLUTION", [v["code"] for v in report["violations"]])

    def test_bundle_tier_and_thirtytwo_control_reuse(self):
        case, evidence = load_fixture("06_bundle_reuse")
        plan = buy_best(case, evidence, include_judgement=True)
        self.assertEqual(plan["selected_actions"], ["act_broad_shared_report"])
        judgement = plan["judgement"]
        self.assertEqual(judgement["control_count"], 32)
        self.assertTrue(judgement["proven"])
        self.assertTrue(all(c["proven"] for c in judgement["controls"]))
        self.assertTrue(
            all(c["covered_union"] == [[100, 900]] for c in judgement["controls"])
        )

        two_labs = price_selection(case, ["act_lab_a", "act_lab_b"])
        three_labs = price_selection(case, ["act_lab_a", "act_lab_b", "act_lab_c"])
        self.assertEqual(two_labs["breakdown"]["batches"]["lab_batch"]["cost"], 12)
        self.assertEqual(three_labs["breakdown"]["batches"]["lab_batch"]["cost"], 12)
        self.assertEqual(two_labs["purchase_count"], 2)
        self.assertEqual(three_labs["purchase_count"], 3)

    def test_quote_scope_does_not_create_coverage(self):
        case, evidence = load_fixture("06_bundle_reuse")
        report = check_solution(case, evidence, ["act_cheap_but_quoted_universal"])
        self.assertFalse(report["ok"])
        infeasible = next(v for v in report["violations"] if v["code"] == "INFEASIBLE_SOLUTION")
        # The cheap action really proves only C_01, so 31 controls fail.
        self.assertEqual(len(infeasible["failed_controls"]), 31)

    def test_bitset_compiler_matches_full_judge_for_every_small_subset(self):
        case, evidence = load_fixture("03_trap_alpha")
        compiler = FeasibilityBitset(case, evidence)
        engine = JudgeEngine(case, evidence)
        action_ids = sorted(a["id"] for a in case["actions"])
        for mask in range(1 << len(action_ids)):
            granted = {
                eid
                for i, aid in enumerate(action_ids)
                if mask & (1 << i)
                for eid in next(a for a in case["actions"] if a["id"] == aid).get("grants", [])
            }
            full = engine.judge(granted)["proven"]
            self.assertEqual(compiler.mask_is_feasible(mask), full, msg=f"mask={mask}")

    def test_eighteen_action_exhaustive_run_is_fast(self):
        controls = [
            {
                "id": f"C{i:02d}",
                "required_intervals": [[0, 100]],
                "required_regions": ["*"],
                "rule": {"kinds": ["annual_report"]},
            }
            for i in range(40)
        ]
        actions = []
        nodes = {}
        for i in range(18):
            eid = f"E{i:02d}"
            actions.append({"id": f"a{i:02d}", "grants": [eid], "cost": i + 1, "review_days": 1})
            nodes[eid] = {
                "id": eid,
                "kind": "annual_report",
                "available": False,
                "approved_regions": ["*"],
                "coverage": [{"controls": "*", "intervals": [[0, 100]]}],
            }
        case = {"case_id": "stress18", "controls": controls, "actions": actions}
        start = time.perf_counter()
        plan = buy_best(case, nodes, include_judgement=False)
        elapsed = time.perf_counter() - start
        self.assertTrue(plan["feasible"])
        self.assertEqual(plan["selected_actions"], ["a00"])
        self.assertEqual(plan["enumeration"]["subsets_considered"], 1 << 18)
        self.assertLess(elapsed, 10.0)


if __name__ == "__main__":
    unittest.main()
