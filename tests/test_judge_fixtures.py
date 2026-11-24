import json
import unittest
from pathlib import Path

from proofmarket.judge import judge_case
from proofmarket.loader import load_case, load_evidence

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


def judge_fixture(name: str):
    case = load_case(FIX / name / "case.json")
    evidence = load_evidence(FIX / name / "evidence.json")
    return judge_case(case, evidence)


class JudgeFixtureTests(unittest.TestCase):
    def test_basic_annual_report_and_first_missing_dependency(self):
        result = judge_fixture("01_basic_graph")
        by_id = {c["id"]: c for c in result["controls"]}
        self.assertTrue(by_id["C_ANNUAL"]["proven"])
        self.assertEqual(by_id["C_ANNUAL"]["covered_union"], [[0, 100]])

        composite = by_id["C_COMPOSITE"]
        self.assertFalse(composite["proven"])
        dep = composite["first_unprovable_dependency"]
        self.assertEqual(dep["evidence_id"], "E_VENDOR_COMPOSITE_V2")
        self.assertEqual(dep["dependency_id"], "E_MISSING_NOT_COMMITTED")
        self.assertEqual(
            dep["dependency_path"],
            ["E_VENDOR_COMPOSITE_V2", "E_MISSING_NOT_COMMITTED"],
        )
        self.assertEqual(composite["counterexample"]["kind"], "uncovered_time")
        self.assertEqual(composite["counterexample"]["at"], 0)

    def test_two_legal_units_of_same_owner_are_not_independent(self):
        result = judge_fixture("02_legal_split")
        control = result["controls"][0]
        self.assertFalse(control["proven"])
        self.assertEqual(control["covered_union"], [])
        diagnostic = control["counterexample"]["diagnostic"]
        self.assertIn("common_owner", diagnostic["reason"])
        self.assertEqual(set(diagnostic["owners"].values()), {"ACTUAL_GROUP_A"})

    def test_temporary_merger_on_billion_axis(self):
        result = judge_fixture("05_merger_huge")
        timewise, stable = result["controls"]
        expected = [[0, 400_000_000], [600_000_000, 1_000_000_000]]
        self.assertEqual(timewise["covered_union"], expected)
        self.assertFalse(timewise["proven"])
        self.assertEqual(timewise["counterexample"]["at"], 400_000_000)
        self.assertIn("TEMP_PARENT", timewise["counterexample"]["reason"])

        alt = stable["alternatives"][0]
        self.assertTrue(alt["stable_pair_required"])
        self.assertIsNone(alt["stable_pair"])
        self.assertEqual(stable["covered_union"], expected)
        self.assertEqual(stable["certified_union"], [])
        self.assertEqual(alt["certified_union"], [])
        self.assertEqual(
            alt["stable_pair_error"]["first_failure"]["interval"],
            [400_000_000, 600_000_000],
        )

    def test_reuse_fixture_has_32_controls_and_broad_coverage(self):
        result = judge_fixture("06_bundle_reuse")
        self.assertEqual(result["control_count"], 32)
        # Evidence is catalog-unavailable until bought, so direct judgement is
        # not proven; the broad node nevertheless has exact full coverage.
        self.assertEqual(result["proven_count"], 0)
        with (FIX / "06_bundle_reuse" / "evidence.json").open(encoding="utf-8") as f:
            raw = json.load(f)
        broad = next(n for n in raw["nodes"] if n["id"] == "E_BROAD_SHARED")
        self.assertEqual(broad["coverage"][0]["controls"], "*")


if __name__ == "__main__":
    unittest.main()
