"""Versioned evidence-graph judgement and exact interval witnesses."""
from __future__ import annotations

import itertools
from typing import Any

from .intervals import (
    Interval,
    cells_between,
    contains_union,
    first_gap,
    interval_contains,
    normalize,
    parse_intervals,
    to_json,
)
from .ownership import OwnershipIndex


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _region_set(value: Any) -> set[str]:
    if value is None:
        return {"*"}
    if isinstance(value, str):
        return {value}
    return {str(v) for v in value}


def intersect_wildcard_regions(*sets: set[str]) -> set[str]:
    concrete: set[str] | None = None
    for current in sets:
        if "*" in current:
            continue
        concrete = set(current) if concrete is None else concrete & current
    return {"*"} if concrete is None else concrete


def is_composite_node(node: dict[str, Any]) -> bool:
    node_type = str(node.get("type", "")).lower()
    return node_type in ("composite", "commitment", "aggregate") or bool(
        node.get("prerequisites") or node.get("requires") or node.get("upstreams")
    )


def claim_records(node: dict[str, Any]) -> list[dict[str, Any]]:
    coverage = node.get("coverage")
    if isinstance(coverage, dict):
        return [coverage]
    if isinstance(coverage, list) and coverage:
        return [c for c in coverage if isinstance(c, dict)]
    if "covers" in node or "control_ids" in node or "controls" in node:
        return [
            {
                "controls": node.get("covers", node.get("control_ids", node.get("controls"))),
                "regions": node.get("coverage_regions", node.get("regions")),
                "intervals": node.get("intervals", node.get("coverage_intervals")),
            }
        ]
    return []


def claim_controls(claim: dict[str, Any]) -> list[str] | str | None:
    return claim.get("controls", claim.get("control_ids", claim.get("control")))


def node_covers_control(node: dict[str, Any], control: dict[str, Any]) -> bool:
    cid = control["id"]
    for claim in claim_records(node):
        controls = claim_controls(claim)
        if controls is None or controls == "*":
            return True
        if isinstance(controls, str):
            if controls == "*" or controls == cid:
                return True
        elif cid in controls:
            return True
        tags = claim.get("control_tags", claim.get("tags"))
        if tags:
            tag_set = set(_as_list(tags))
            if tag_set & set(control.get("tags", [])):
                return True
    return False


def effective_coverage(node: dict[str, Any], control: dict[str, Any]) -> list[Interval]:
    """Actual approved/claimed time coverage for one control and region."""
    out: list[Interval] = []
    cid = control["id"]
    required_regions = _region_set(control.get("required_regions", ["*"]))
    for claim in claim_records(node):
        controls = claim_controls(claim)
        controls_ok = controls is None or controls == "*"
        if isinstance(controls, str):
            controls_ok = controls in ("*", cid)
        elif isinstance(controls, list):
            controls_ok = cid in controls
        if not controls_ok:
            tags = claim.get("control_tags", claim.get("tags"))
            controls_ok = bool(tags and set(_as_list(tags)) & set(control.get("tags", [])))
        if not controls_ok:
            continue

        claim_regions = _region_set(claim.get("regions", claim.get("region", ["*"])))
        approved_regions = _region_set(
            node.get("approved_regions", node.get("approval_regions", claim_regions))
        )
        common = intersect_wildcard_regions(claim_regions, approved_regions, required_regions)
        if not common:
            continue
        ivs = parse_intervals(
            claim.get("intervals", claim.get("interval", node.get("intervals", []))),
            f"evidence.{node.get('id')}.coverage",
        )
        out.extend(ivs)
    from .intervals import normalize

    return normalize(out)


class JudgeEngine:
    def __init__(self, case: dict[str, Any], nodes: dict[str, dict[str, Any]]):
        self.case = case
        self.nodes = nodes
        self.ownership = OwnershipIndex(case.get("ownership_intervals", []))
        self.decision_time = case.get("decision_time", case.get("as_of"))
        self._status_cache: dict[tuple[str, frozenset[str] | None], dict[str, Any]] = {}

    # ---------- graph validity ----------

    def is_active(self, node: dict[str, Any], granted: set[str] | None) -> bool:
        nid = node["id"]
        if granted is not None and nid in granted:
            return True
        return bool(node.get("available", True))

    def status(self, nid: str, granted: set[str] | None = None, _stack: tuple[str, ...] = ()) -> dict[str, Any]:
        cache_key = (nid, None if granted is None else frozenset(granted))
        if not _stack and cache_key in self._status_cache:
            return self._status_cache[cache_key]

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            if not _stack:
                self._status_cache[cache_key] = result
            return result

        if nid in _stack:
            idx = _stack.index(nid)
            cycle_path = list(_stack[idx:]) + [nid]
            return finish(
                {
                    "id": nid,
                    "valid": False,
                    "reason": "cycle",
                    "first_bad_id": nid,
                    # Return only the repeated id; callers prepend their ids,
                    # producing one clean path such as ROOT,A,B,A.
                    "dependency_path": [nid],
                    "cycle_path": cycle_path,
                }
            )
        node = self.nodes.get(nid)
        if node is None:
            return finish(
                {
                    "id": nid,
                    "valid": False,
                    "reason": "missing_evidence",
                    "first_bad_id": nid,
                    "dependency_path": [nid],
                }
            )
        if not self.is_active(node, granted):
            return finish(
                {
                    "id": nid,
                    "valid": False,
                    "reason": "not_purchased_or_unavailable",
                    "first_bad_id": nid,
                    "dependency_path": [nid],
                }
            )
        if self.decision_time is not None:
            known_at = node.get("known_at", node.get("available_at"))
            if isinstance(known_at, int) and not isinstance(known_at, bool) and known_at > self.decision_time:
                return finish(
                    {
                        "id": nid,
                        "valid": False,
                        "reason": "not_knowable_at_decision_time",
                        "first_bad_id": nid,
                        "dependency_path": [nid],
                    }
                )
        if node.get("revoked", False) or node.get("status") == "revoked":
            return finish(
                {
                    "id": nid,
                    "valid": False,
                    "reason": "revoked",
                    "first_bad_id": nid,
                    "dependency_path": [nid],
                }
            )
        prereqs = [p for p in node.get("prerequisites", []) if isinstance(p, str)]
        node_type = str(node.get("type", "")).lower()
        is_composite = node_type in ("composite", "commitment", "aggregate") or bool(prereqs)
        if not is_composite and node.get("signed", True) is False:
            return finish(
                {
                    "id": nid,
                    "valid": False,
                    "reason": "unsigned_leaf_receipt",
                    "first_bad_id": nid,
                    "dependency_path": [nid],
                }
            )
        for pre in prereqs:
            pre_status = self.status(pre, granted, _stack + (nid,))
            if not pre_status["valid"]:
                path = [nid] + pre_status.get("dependency_path", [pre])
                root_reason = pre_status.get("root_reason", pre_status["reason"])
                return finish(
                    {
                        "id": nid,
                        "valid": False,
                        "reason": "prerequisite_invalid:" + root_reason,
                        "root_reason": root_reason,
                        "first_bad_id": pre_status.get("first_bad_id", pre),
                        "dependency_path": path,
                    }
                )
        return finish(
            {
                "id": nid,
                "valid": True,
                "reason": "valid",
                "first_bad_id": None,
                "dependency_path": [nid],
            }
        )

    def anchor_ids(self, nid: str, granted: set[str] | None = None) -> set[str]:
        """Leaf receipt ids anchoring a possibly composite commitment."""
        seen: set[str] = set()
        anchors: set[str] = set()

        def visit(x: str) -> None:
            if x in seen:
                return
            seen.add(x)
            node = self.nodes.get(x)
            if node is None:
                anchors.add(x)
                return
            prereqs = [p for p in node.get("prerequisites", []) if isinstance(p, str)]
            if not prereqs:
                anchors.add(x)
            for p in prereqs:
                visit(p)

        visit(nid)
        return anchors

    def graph_independent(self, a: str, b: str) -> tuple[bool, str | None]:
        if a == b:
            return False, "same_evidence"
        # Ancestor/descendant cannot be two independent sources.
        if b in self._reachable_prerequisites(a) or a in self._reachable_prerequisites(b):
            return False, "dependency_ancestor"
        aa = self.anchor_ids(a)
        ab = self.anchor_ids(b)
        shared = aa & ab
        if shared:
            return False, "shared_anchor:" + ",".join(sorted(shared))
        return True, None

    def _reachable_prerequisites(self, nid: str) -> set[str]:
        out: set[str] = set()
        stack = [nid]
        while stack:
            x = stack.pop()
            node = self.nodes.get(x)
            if not node:
                continue
            for p in node.get("prerequisites", []):
                if p not in out:
                    out.add(p)
                    stack.append(p)
        return out

    # ---------- alternatives ----------

    def alternatives(self, control: dict[str, Any]) -> list[dict[str, Any]]:
        rule = control.get("rule") or control.get("proof") or {}
        if isinstance(rule, str):
            rule = {"id": rule, "preset": rule}
        alts = rule.get("alternatives") if isinstance(rule, dict) else None
        if alts is None:
            alts = [rule if isinstance(rule, dict) else {}]
        result = []
        for i, raw in enumerate(alts):
            alt = dict(raw) if isinstance(raw, dict) else {}
            alt.setdefault("id", alt.get("name", f"alternative-{i + 1}"))
            if "kinds" not in alt and "kind" in alt:
                alt["kinds"] = _as_list(alt["kind"])
            alt.setdefault("kinds", [])
            alt["kinds"] = [str(k) for k in alt["kinds"]]
            alt.setdefault("quorum", int(alt.get("independent_sources", 1) or 1))
            if alt.get("independent") is None:
                alt["independent"] = bool(alt.get("require_independent_sources", alt["quorum"] >= 2))
            policy = alt.get("coverage_policy", alt.get("combination", "at_each_time"))
            alt["coverage_policy"] = policy
            alt["stable_pair_required"] = bool(
                alt.get("same_pair_required", policy in ("same_pair", "same_pair_full_span", "shared_period"))
            )
            result.append(alt)
        return result

    def _matches_predicate(self, node: dict[str, Any], alt: dict[str, Any]) -> bool:
        if alt["kinds"] and node.get("kind") not in alt["kinds"]:
            return False
        tags = set(_as_list(node.get("tags")))
        need_all = set(_as_list(alt.get("tags_all", alt.get("tags", []))))
        if need_all and not need_all <= tags:
            return False
        need_any = set(_as_list(alt.get("tags_any", [])))
        if need_any and not (need_any & tags):
            return False
        ids = alt.get("evidence_ids", alt.get("ids"))
        if ids is not None and node["id"] not in set(_as_list(ids)):
            return False
        return True

    def _candidate_data(
        self, control: dict[str, Any], alt: dict[str, Any], granted: set[str] | None
    ) -> list[dict[str, Any]]:
        candidates = []
        independent_quorum = bool(alt.get("independent")) and max(1, int(alt.get("quorum", 1))) >= 2
        allow_composite = bool(alt.get("allow_composite_sources", False))
        for node in sorted(self.nodes.values(), key=lambda n: n.get("_order", 0)):
            if not self._matches_predicate(node, alt):
                continue
            if independent_quorum and not allow_composite and is_composite_node(node):
                # Distinct upstream commitments are not themselves a pair of
                # independent laboratory leaves.
                continue
            status = self.status(node["id"], granted)
            cov = effective_coverage(node, control)
            from .intervals import intersect_all_unions

            cov = intersect_all_unions(cov, control["required_intervals"])
            if status["valid"] and cov:
                candidates.append(
                    {
                        "id": node["id"],
                        "source": node.get("source"),
                        "coverage": cov,
                        "order": node.get("_order", 0),
                    }
                )
        return candidates

    def _cell_endpoints(self, required: list[Interval], candidates: list[dict[str, Any]]) -> list[int]:
        eps: set[int] = set()
        for iv in required:
            eps.update(iv)
        for cand in candidates:
            for a, b in cand["coverage"]:
                eps.add(a)
                eps.add(b)
                source = cand["source"]
                for entity in (source,):
                    for a, b in self.ownership.timelines.get(entity, []):
                        # Include only ownership segments that can matter.
                        if any(max(a, ra[0]) < min(b, ra[1]) for ra in required):
                            eps.add(a)
                            eps.add(b)
        return sorted(eps)

    def _combo_passes(
        self, combo: tuple[dict[str, Any], ...], at: int, require_independence: bool = True
    ) -> tuple[bool, str | None, list[str]]:
        for cand in combo:
            if not interval_contains(cand["coverage"], at):
                return False, "coverage_missing", []
        if len(combo) == 1 or not require_independence:
            return True, None, [combo[0]["id"]] if len(combo) == 1 else [c["id"] for c in combo]
        owners = []
        for cand in combo:
            owner = self.ownership.owner_at(cand["source"], at)
            if owner is None:
                return False, "unknown_owner", []
            owners.append(owner)
        if len(set(owners)) != len(owners):
            return False, "common_owner:" + ",".join(owners), []
        for x, y in itertools.combinations(combo, 2):
            ok, reason = self.graph_independent(x["id"], y["id"])
            if not ok:
                return False, reason, []
        return True, None, [c["id"] for c in combo]

    def evaluate_alternative(
        self, control: dict[str, Any], alt: dict[str, Any], granted: set[str] | None = None
    ) -> dict[str, Any]:
        required = control["required_intervals"]
        candidates = self._candidate_data(control, alt, granted)
        q = max(1, int(alt.get("quorum", 1)))
        covered_cells: list[Interval] = []
        witnesses: list[dict[str, Any]] = []
        failure_at: dict[int, dict[str, Any]] = {}
        endpoints = self._cell_endpoints(required, candidates)

        for req_iv in required:
            for lo, hi in cells_between(req_iv[0], req_iv[1], endpoints):
                at = lo
                passing = None
                failure_reason = "insufficient_independent_evidence"
                if len(candidates) >= q:
                    for indices in itertools.combinations(range(len(candidates)), q):
                        combo = tuple(candidates[i] for i in indices)
                        ok, reason, ids = self._combo_passes(
                            combo, at, bool(alt.get("independent"))
                        )
                        if ok:
                            passing = ids
                            break
                        failure_reason = reason or failure_reason
                elif not candidates:
                    failure_reason = "no_qualifying_valid_evidence"
                else:
                    failure_reason = "quorum_not_available"
                if passing is not None:
                    covered_cells.append((lo, hi))
                    if not witnesses:
                        witnesses.append(
                            {
                                "at": at,
                                "interval": [lo, hi],
                                "evidence_ids": passing,
                                "sources": [
                                    next(c["source"] for c in candidates if c["id"] == eid)
                                    for eid in passing
                                ],
                                "owners": [
                                    self.ownership.owner_at(
                                        next(c["source"] for c in candidates if c["id"] == eid), at
                                    )
                                    for eid in passing
                                ],
                            }
                        )
                else:
                    failure_at[at] = {
                        "at": at,
                        "interval": [lo, hi],
                        "reason": failure_reason,
                        "candidate_ids": [c["id"] for c in candidates],
                        "owners": {
                            c["id"]: self.ownership.owner_at(c["source"], at) for c in candidates
                        },
                    }

        from .intervals import normalize

        covered = normalize(covered_cells)
        stable_pair = None
        stable_error = None
        if alt.get("independent") and q == 2:
            for i, j in itertools.combinations(range(len(candidates)), 2):
                a, b = candidates[i], candidates[j]
                pair_union = []
                pair_failure = None
                for req_iv in required:
                    for lo, hi in cells_between(req_iv[0], req_iv[1], endpoints):
                        ok, reason, _ = self._combo_passes((a, b), lo)
                        if ok:
                            pair_union.append((lo, hi))
                        elif pair_failure is None:
                            pair_failure = {"at": lo, "interval": [lo, hi], "reason": reason}
                pair_union = normalize(pair_union)
                if contains_union(required, pair_union):
                    stable_pair = {
                        "evidence_ids": [a["id"], b["id"]],
                        "sources": [a["source"], b["source"]],
                    }
                    break
                if stable_error is None and pair_failure is not None:
                    stable_error = {
                        "pair": [a["id"], b["id"]],
                        "first_failure": pair_failure,
                        "valid_union": to_json(pair_union),
                    }
        proven = contains_union(required, covered)
        stable_required = bool(alt.get("stable_pair_required"))
        if stable_required:
            proven = proven and stable_pair is not None
        certified_union = required if stable_required and stable_pair else ([] if stable_required else covered)

        return {
            "id": alt["id"],
            "kinds": alt["kinds"],
            "quorum": q,
            "independent": bool(alt.get("independent")),
            "coverage_policy": alt.get("coverage_policy"),
            "stable_pair_required": stable_required,
            "proven": proven,
            "covered_union": to_json(covered),
            "local_endpoint_union": to_json(covered),
            "certified_union": to_json(certified_union),
            "candidate_ids": [c["id"] for c in candidates],
            "witness": witnesses[0] if witnesses else None,
            "stable_pair": stable_pair,
            "stable_pair_error": None if stable_pair else stable_error,
            "diagnostic_at_first_failure": failure_at[min(failure_at)] if failure_at else None,
        }

    def first_graph_failure_for_control(
        self, control: dict[str, Any], granted: set[str] | None = None
    ) -> dict[str, Any] | None:
        related = [
            node
            for node in sorted(self.nodes.values(), key=lambda n: n.get("_order", 0))
            if node_covers_control(node, control)
        ]
        for node in related:
            st = self.status(node["id"], granted)
            if not st["valid"]:
                return {
                    "evidence_id": node["id"],
                    "dependency_id": st.get("first_bad_id"),
                    "reason": st["reason"],
                    "dependency_path": st.get("dependency_path", [node["id"]]),
                }
        # A predicate may match no node at all.  Report the first invalid node
        # of a predicate-matching kind so missing prerequisites are still found.
        for alt in self.alternatives(control):
            for node in sorted(self.nodes.values(), key=lambda n: n.get("_order", 0)):
                if self._matches_predicate(node, alt):
                    st = self.status(node["id"], granted)
                    if not st["valid"]:
                        return {
                            "evidence_id": node["id"],
                            "dependency_id": st.get("first_bad_id"),
                            "reason": st["reason"],
                            "dependency_path": st.get("dependency_path", [node["id"]]),
                        }
        return None

    def counterexample(
        self,
        control: dict[str, Any],
        alt_results: list[dict[str, Any]],
        graph_failure: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        required = control["required_intervals"]
        # Choose the alternative with the lexicographically earliest gap; this
        # gives a stable minimum witness instead of an arbitrary failure.
        best_gap: Interval | None = None
        best_alt = None
        for ar in alt_results:
            covered = [[a, b] for a, b in ar["covered_union"]]
            gap = first_gap(required, covered)
            if gap is not None and (best_gap is None or gap[0] < best_gap[0]):
                best_gap = gap
                best_alt = ar
        if best_gap is not None:
            at = best_gap[0]
            diag = best_alt.get("diagnostic_at_first_failure")
            if diag is None or diag.get("at") != at:
                diag = {
                    "at": at,
                    "interval": [best_gap[0], best_gap[1]],
                    "reason": "not_covered_by_selected_alternative",
                }
            reason = diag.get("reason")
            if graph_failure is not None and reason in (
                "no_qualifying_valid_evidence",
                "quorum_not_available",
                "insufficient_independent_evidence",
            ):
                reason = "dependency_not_provable:" + graph_failure["reason"]
            return {
                "kind": "uncovered_time",
                "alternative_id": best_alt["id"],
                "at": at,
                "minimum_witness": {"time": at, "half_open_cell": diag.get("interval", [best_gap[0], best_gap[1]])},
                "elementary_interval": diag.get("interval", [best_gap[0], best_gap[1]]),
                "maximal_gap": [best_gap[0], best_gap[1]],
                "reason": reason,
                "diagnostic": diag,
                "unprovable_dependency": graph_failure,
                "verification": [
                    {"check": "at_in_required_union", "at": at, "result": True},
                    {"check": "at_in_covered_union", "at": at, "result": False},
                    {"check": "endpoint_arithmetic", "interval": [best_gap[0], best_gap[1]], "half_open": "[start,end)"},
                ],
            }
        for ar in alt_results:
            if ar["stable_pair_required"] and not ar["stable_pair"]:
                err = ar.get("stable_pair_error") or {}
                failure = err.get("first_failure") or {}
                at = failure.get("at")
                return {
                    "kind": "no_stable_independent_pair",
                    "alternative_id": ar["id"],
                    "at": at,
                    "elementary_interval": failure.get("interval"),
                    "blocking_pair": err.get("pair"),
                    "reason": failure.get("reason", "stable_pair_required"),
                    "stable_pair_error": err,
                    "verification": [
                        {"check": "one_pair_must_cover_full_required_union", "result": False},
                        {"check": "ownership_and_graph_checked_at_endpoint_cells", "result": True},
                    ],
                }
        if graph_failure is not None:
            return {
                "kind": "unprovable_dependency",
                "at": None,
                "dependency": graph_failure,
                "verification": [
                    {"check": "all_prerequisites_must_be_valid", "result": False},
                    {"check": "composite_covers_nothing_when_any_prerequisite_fails", "result": True},
                ],
            }
        return None

    def judge_control(self, control: dict[str, Any], granted: set[str] | None = None) -> dict[str, Any]:
        alts = self.alternatives(control)
        alt_results = [self.evaluate_alternative(control, alt, granted) for alt in alts]
        proven_alt = next((ar for ar in alt_results if ar["proven"]), None)
        if proven_alt:
            covered = proven_alt["covered_union"]
            certified = proven_alt["certified_union"]
            proven = True
        else:
            from .intervals import union_all

            covered = to_json(union_all([tuple(iv) for ar in alt_results for iv in ar["covered_union"]]))
            certified = to_json(union_all([tuple(iv) for ar in alt_results for iv in ar["certified_union"]]))
            proven = False
        graph_failure = self.first_graph_failure_for_control(control, granted)
        actual_union: list[Interval] = []
        for node in sorted(self.nodes.values(), key=lambda n: n.get("_order", 0)):
            if not node_covers_control(node, control):
                continue
            if self.status(node["id"], granted)["valid"]:
                actual_union.extend(effective_coverage(node, control))
        actual_union = normalize(actual_union)
        counter = None if proven else self.counterexample(control, alt_results, graph_failure)
        return {
            "id": control["id"],
            "risk_class": control.get("risk_class"),
            "proven": proven,
            "required_union": to_json(control["required_intervals"]),
            "covered_union": covered,
            "certified_union": certified,
            "actual_valid_evidence_union": to_json(actual_union),
            "gaps": to_json(first_gap_many(control["required_intervals"], covered)),
            "selected_alternative": proven_alt["id"] if proven_alt else None,
            "witness": proven_alt.get("witness") if proven_alt else None,
            "stable_pair": proven_alt.get("stable_pair") if proven_alt else None,
            "alternatives": alt_results,
            "counterexample": counter,
            "minimal_verifiable_counterexample": counter,
            "first_unprovable_dependency": graph_failure,
        }

    def judge(self, granted: set[str] | None = None) -> dict[str, Any]:
        # A judgement is one consistent availability world.  Reset the memo so
        # buy enumeration cannot accumulate one cache per 2**18 subset.
        self._status_cache = {}
        controls = [self.judge_control(c, granted) for c in self.case["controls"]]
        proven = all(c["proven"] for c in controls)
        first_dep = next(
            (c["first_unprovable_dependency"] for c in controls if c["first_unprovable_dependency"]),
            None,
        )
        first_counter = next((c["counterexample"] for c in controls if c["counterexample"]), None)
        return {
            "schema": "proofmarket.judgement.v1",
            "case_id": self.case.get("case_id"),
            "proven": proven,
            "control_count": len(controls),
            "proven_count": sum(c["proven"] for c in controls),
            "first_unprovable_dependency": first_dep,
            "first_counterexample": first_counter,
            "minimal_verifiable_counterexample": first_counter,
            "controls": controls,
        }


def first_gap_many(required: list[Interval], covered_json: list[list[int]]) -> list[Interval]:
    from .intervals import subtract_union

    covered = [(a, b) for a, b in covered_json]
    return subtract_union(required, covered)


def judge_case(
    case: dict[str, Any], nodes: dict[str, dict[str, Any]], granted: set[str] | None = None
) -> dict[str, Any]:
    return JudgeEngine(case, nodes).judge(granted)
