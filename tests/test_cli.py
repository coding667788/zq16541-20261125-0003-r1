import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str):
        proc = subprocess.run(
            [sys.executable, "-I", str(ROOT / "proofmarket.py"), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return proc

    def test_judge_outputs_utf8_json(self):
        proc = self.run_cli(
            "judge",
            str(FIX / "05_merger_huge" / "case.json"),
            str(FIX / "05_merger_huge" / "evidence.json"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema"], "proofmarket.judgement.v1")
        self.assertIn("TEMP_PARENT", proc.stdout)

    def test_buy_outputs_plan(self):
        proc = self.run_cli(
            "buy",
            str(FIX / "03_trap_alpha" / "case.json"),
            str(FIX / "03_trap_alpha" / "evidence.json"),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["feasible"])
        self.assertEqual(payload["selected_actions"][0], "act_p_a1_cheap")

    def test_check_rejection_uses_nonzero_exit_and_json(self):
        proc = self.run_cli(
            "check",
            str(FIX / "04_trap_beta" / "case.json"),
            str(FIX / "04_trap_beta" / "evidence.json"),
            str(FIX / "04_trap_beta" / "solution-false-upstreams.json"),
        )
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["violations"])


if __name__ == "__main__":
    unittest.main()
