from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .buy import buy_best
from .check import check_solution
from .intervals import InputError
from .judge import judge_case
from .loader import load_case, load_evidence, read_json


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def emit(payload: Any, out: str | Path | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proofmarket",
        description="Offline multi-party evidence judgement, procurement and checking.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_judge = sub.add_parser("judge", help="Judge CASE against an EVIDENCE graph")
    p_judge.add_argument("case", nargs="?")
    p_judge.add_argument("evidence", nargs="?")
    p_judge.add_argument("--case", dest="case_opt")
    p_judge.add_argument("--evidence", dest="evidence_opt")
    p_judge.add_argument("--out")

    p_buy = sub.add_parser("buy", help="Exhaustively choose at most 18 purchase actions")
    p_buy.add_argument("case", nargs="?")
    p_buy.add_argument("evidence", nargs="?")
    p_buy.add_argument("--case", dest="case_opt")
    p_buy.add_argument("--evidence", dest="evidence_opt")
    p_buy.add_argument("--max-actions", type=int, default=18)
    p_buy.add_argument("--out")

    p_check = sub.add_parser("check", help="Verify a proposed solution and optimality")
    p_check.add_argument("case", nargs="?")
    p_check.add_argument("evidence", nargs="?")
    p_check.add_argument("solution", nargs="?")
    p_check.add_argument("--case", dest="case_opt")
    p_check.add_argument("--evidence", dest="evidence_opt")
    p_check.add_argument("--solution", dest="solution_opt")
    p_check.add_argument("--out")
    return parser


def _positional_or_opt(pos: str | None, opt: str | None, name: str) -> str:
    value = pos or opt
    if not value:
        raise InputError(f"missing {name} path")
    return value


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "judge":
            case_path = _positional_or_opt(args.case, args.case_opt, "CASE")
            evidence_path = _positional_or_opt(args.evidence, args.evidence_opt, "EVIDENCE")
            case = load_case(case_path)
            nodes = load_evidence(evidence_path)
            result = judge_case(case, nodes)
            emit(result, args.out)
            return 0

        if args.command == "buy":
            case_path = _positional_or_opt(args.case, args.case_opt, "CASE")
            evidence_path = args.evidence or args.evidence_opt
            case = load_case(case_path)
            if evidence_path:
                nodes = load_evidence(evidence_path)
            else:
                evidence_ref = case.get("evidence_file") or case.get("evidence", {})
                if isinstance(evidence_ref, str) and not Path(evidence_ref).is_absolute():
                    evidence_ref = str((Path(case_path).parent / evidence_ref).resolve())
                nodes = load_evidence(evidence_ref)
            result = buy_best(case, nodes, max_actions=args.max_actions)
            emit(result, args.out)
            return 0

        if args.command == "check":
            case_path = _positional_or_opt(args.case, args.case_opt, "CASE")
            evidence_path = _positional_or_opt(args.evidence, args.evidence_opt, "EVIDENCE")
            solution_path = _positional_or_opt(args.solution, args.solution_opt, "SOLUTION")
            case = load_case(case_path)
            nodes = load_evidence(evidence_path)
            solution = read_json(solution_path)
            result = check_solution(case, nodes, solution)
            emit(result, args.out)
            return 0 if result["ok"] else 1

        parser.error(f"unknown command {args.command}")
        return 2
    except (InputError, OSError, ValueError) as exc:
        emit({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
