"""Independent verification of proposed procurement solutions."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import itertools

from .buy import action_by_id, buy_best, granted_evidence, price_selection
from .intervals import cells_between, parse_intervals, to_json
from .judge import JudgeEngine
from .loader import load_case, load_evidence, read_json


def load_solution(path_or_data: str | Path | dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(path_or_data, (str, Path)):
        data = read_json(path_or_data)
    else:
        data = path_or_data
    if isinstance(data, list):
        return {"selected_actions": data}
    if not isinstance(data, dict):
        raise ValueError("SOLUTION must be a JSON object or array")
    if "plan" in data and isinstance(data["plan"], dict):
        merged = dict(data)
        for key in (
            "selected_actions",
            "selected_ids",
            "independence_claims",
            "source_claims",
            "independent_pairs",
            "source_assignments",
            "assignments",
        ):
            if key in data["plan"] and key not in merged:
                merged[key] = data["plan"][key]
        data = merged
    return data


def extract_selected(solution: dict[str, Any]) -> list[str]:
    for key in ("selected_actions", "selected_ids", "actions", "purchase_ids"):
        value = solution.get(key)
        if isinstance(value, list):
            return [str(x) for x in value]
        if isinstance(value, str):
            return [value]
    return []


def extract_claims(solution: dict[str, Any]) -> list[dict[str, Any]]:
    claims = solution.get(
        "independence_claims",
        solution.get(
            "source_claims",
            solution.get(
                "independent_pairs",
                solution.get(
                    "source_assignments",
                    solution.get("assignments", solution.get("claims", [])),
                ),
            ),
        ),
    )
    if isinstance(claims, dict):
        claims = [claims]
    return [c for c in claims if isinstance(c, dict)] if isinstance(claims, list) else []


def _claim_pair(claim: dict[str, Any]) -> list[str]:
    for key in ("evidence", "evidence_ids", "sources", "source_ids", "pair"):
        if key in claim:
            value = claim[key]
            if isinstance(value, list):
                return [str(x) for x in value]
            if isinstance(value, str):
                return [value]
    if "upstreams" in claim:
        value = claim["upstreams"]
        if isinstance(value, list):
            return [str(x) for x in value]
    return []


def verify_independence_claim(
    claim: dict[str, Any],
    case: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    engine: JudgeEngine,
) -> dict[str, Any]:
    pair = _claim_pair(claim)
    control_id = claim.get("control", claim.get("control_id"))
    control = next((c for c in case["controls"] if c["id"] == control_id), None) if control_id else None
    raw_span = claim.get("interval", claim.get("intervals"))
    if isinstance(raw_span, tuple) or (
        isinstance(raw_span, list) and len(raw_span) == 2 and not isinstance(raw_span[0], (list, dict))
    ):
        span = parse_intervals([raw_span], "independence_claim.interval")
    else:
        span = parse_intervals(raw_span, "independence_claim.intervals")
    if not span and control is not None:
        span = control["required_intervals"]
    result: dict[str, Any] = {
        "control": control_id,
        "evidence_ids": pair,
        "accepted": False,
        "violations": [],
        "checked_union": to_json(span),
    }
    if len(pair) < 2:
        result["violations"].append(
            {"code": "MALFORMED_INDEPENDENCE_CLAIM", "message": "at least two evidence ids are required"}
        )
        return result

    for eid in pair:
        if eid not in nodes:
            result["violations"].append(
                {"code": "UNKNOWN_EVIDENCE", "evidence_id": eid, "message": "evidence id is absent from EVIDENCE"}
            )
    if any(v["code"] == "UNKNOWN_EVIDENCE" for v in result["violations"]):
        return result

    if "upstreams" in claim and not claim.get("allow_composite"):
        result["violations"].append(
            {
                "code": "UPSTREAM_SOURCES_NOT_INDEPENDENT",
                "evidence_ids": pair,
                "message": (
                    "two distinct upstream commitments of one control/dependency chain are not "
                    "themselves two independent laboratories; trace them to distinct leaf owners"
                ),
            }
        )

    for a, b in itertools.combinations(pair, 2):
        node_a, node_b = nodes[a], nodes[b]
        composite_a = bool(node_a.get("prerequisites")) or str(node_a.get("type", "")).lower() in (
            "composite",
            "commitment",
        )
        composite_b = bool(node_b.get("prerequisites")) or str(node_b.get("type", "")).lower() in (
            "composite",
            "commitment",
        )
        if (composite_a or composite_b) and not claim.get("allow_composite"):
            result["violations"].append(
                {
                    "code": "UPSTREAM_COMMITMENT_CLAIMED_AS_LAB",
                    "evidence_ids": [a, b],
                    "message": "composite upstream commitments must be traced to independent leaf signoffs",
                    "leaf_anchors": {
                        a: sorted(engine.anchor_ids(a)),
                        b: sorted(engine.anchor_ids(b)),
                    },
                }
            )
        graph_ok, graph_reason = engine.graph_independent(a, b)
        if not graph_ok:
            result["violations"].append(
                {
                    "code": "DEPENDENT_EVIDENCE_GRAPH",
                    "evidence_ids": [a, b],
                    "reason": graph_reason,
                    "message": "evidence pair shares an ancestor, anchor, or prerequisite closure",
                }
            )

        sources = [nodes[eid].get("source") for eid in (a, b)]
        endpoints = set()
        for iv in span:
            endpoints.update(iv)
        for source in sources:
            for iv in engine.ownership.timelines.get(source, []):
                endpoints.update(iv)
        points = sorted(endpoints)
        first_common = None
        first_unknown = None
        for lo, hi in zip(points, points[1:]):
            if not any(s <= lo < e for s, e in span):
                continue
            oa = engine.ownership.owner_at(sources[0], lo)
            ob = engine.ownership.owner_at(sources[1], lo)
            if oa is None or ob is None:
                if first_unknown is None:
                    first_unknown = {"interval": [lo, hi], "owners": [oa, ob]}
            elif oa == ob and first_common is None:
                first_common = {"interval": [lo, hi], "owner": oa}
        if first_unknown is not None:
            result["violations"].append(
                {
                    "code": "UNKNOWN_ACTUAL_OWNERSHIP",
                    "evidence_ids": [a, b],
                    "at_interval": first_unknown["interval"],
                    "owners": first_unknown["owners"],
                    "message": "independence cannot be proven without actual ownership",
                }
            )
        if first_common is not None:
            result["violations"].append(
                {
                    "code": "COMMON_OWNERSHIP",
                    "evidence_ids": [a, b],
                    "at_interval": first_common["interval"],
                    "owner": first_common["owner"],
                    "message": "sources have the same actual owner in this interval",
                }
            )
    result["accepted"] = not result["violations"]
    return result


def check_solution(
    case: dict[str, Any] | str,
    evidence: dict[str, dict[str, Any]] | str | None,
    solution: dict[str, Any] | str | list[Any],
) -> dict[str, Any]:
    if isinstance(case, str):
        case = load_case(case)
    else:
        case = load_case(case)
    if isinstance(evidence, (str, Path)) or evidence is None:
        nodes = load_evidence(evidence)
    else:
        nodes = evidence
    if not isinstance(solution, dict):
        solution = load_solution(solution)

    violations: list[dict[str, Any]] = []
    selected = extract_selected(solution)
    actions = action_by_id(case)
    unknown = [aid for aid in selected if aid not in actions]
    duplicates = sorted({aid for aid in selected if selected.count(aid) > 1})
    if unknown:
        violations.append({"code": "UNKNOWN_ACTION", "action_ids": unknown})
    if duplicates:
        violations.append({"code": "DUPLICATE_ACTION", "action_ids": duplicates})
    if len(selected) > 18:
        violations.append({"code": "TOO_MANY_ACTIONS", "count": len(selected), "limit": 18})

    claim_reports = []
    engine = JudgeEngine(case, nodes)
    for claim in extract_claims(solution):
        report = verify_independence_claim(claim, case, nodes, engine)
        claim_reports.append(report)
        if not report["accepted"]:
            violations.append(
                {
                    "code": "FALSE_INDEPENDENCE",
                    "control": report.get("control"),
                    "evidence_ids": report.get("evidence_ids"),
                    "claim_violations": report["violations"],
                }
            )

    candidate_metrics = None
    candidate_judgement = None
    if not unknown and not duplicates:
        candidate_metrics = price_selection(case, selected)
        granted = granted_evidence(case, selected)
        candidate_judgement = engine.judge(granted)
        if not candidate_judgement["proven"]:
            failed = [c["id"] for c in candidate_judgement["controls"] if not c["proven"]]
            violations.append(
                {
                    "code": "INFEASIBLE_SOLUTION",
                    "failed_controls": failed,
                    "first_counterexample": candidate_judgement.get("first_counterexample"),
                    "first_unprovable_dependency": candidate_judgement.get("first_unprovable_dependency"),
                }
            )

    optimal = buy_best(case, nodes, include_judgement=False)
    comparison = {"optimal": None if not optimal.get("feasible") else _public_plan(optimal)}
    if optimal.get("feasible") and candidate_metrics is not None:
        om = optimal["metrics"]
        comparison["optimal"] = _public_plan(optimal)
        same_cost = candidate_metrics["full_period_cost"] == om["full_period_cost"]
        if candidate_metrics["full_period_cost"] > om["full_period_cost"]:
            violations.append(
                {
                    "code": "NOT_MINIMAL_FULL_PERIOD_COST",
                    "candidate_cost": candidate_metrics["full_period_cost"],
                    "optimal_cost": om["full_period_cost"],
                    "optimal_actions": optimal["selected_actions"],
                }
            )
        elif same_cost and candidate_metrics["review_days"] > om["review_days"]:
            violations.append(
                {
                    "code": "REVIEW_DAYS_NOT_MINIMAL",
                    "full_period_cost": om["full_period_cost"],
                    "candidate_review_days": candidate_metrics["review_days"],
                    "optimal_review_days": om["review_days"],
                    "optimal_actions": optimal["selected_actions"],
                    "message": "equal full-period cost but larger manual review burden",
                }
            )
        elif (
            same_cost
            and candidate_metrics["review_days"] == om["review_days"]
            and candidate_metrics["purchase_count"] > om["purchase_count"]
        ):
            violations.append(
                {
                    "code": "PURCHASE_COUNT_NOT_MINIMAL",
                    "candidate_purchase_count": candidate_metrics["purchase_count"],
                    "optimal_purchase_count": om["purchase_count"],
                    "optimal_actions": optimal["selected_actions"],
                }
            )
        elif (
            same_cost
            and candidate_metrics["review_days"] == om["review_days"]
            and candidate_metrics["purchase_count"] == om["purchase_count"]
            and sorted(selected) != optimal["selected_actions"]
        ):
            if tuple(sorted(selected)) > tuple(optimal["selected_actions"]):
                violations.append(
                    {
                        "code": "ID_TIE_BREAK_LOSS",
                        "candidate_ids": sorted(selected),
                        "optimal_ids": optimal["selected_actions"],
                    }
                )

    ok = not violations
    return {
        "schema": "proofmarket.check.v1",
        "case_id": case.get("case_id"),
        "ok": ok,
        "accepted": ok,
        "selected_actions": sorted(selected),
        "candidate_metrics": candidate_metrics,
        "independence_claims": claim_reports,
        "violations": violations,
        "comparison": comparison,
        "candidate_proven": None if candidate_judgement is None else candidate_judgement["proven"],
    }


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "selected_actions": plan["selected_actions"],
        "metrics": plan["metrics"],
        "tie_break_key": plan.get("tie_break_key"),
    }
