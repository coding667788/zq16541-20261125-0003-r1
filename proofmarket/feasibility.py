"""Bitset feasibility compiler for exhaustive procurement.

With at most 18 actions, a procurement subset is an integer mask in
``[0, 2**18)``.  For every evidence node we compile a Python big integer whose
bit *m* is one exactly when that node is valid under mask *m*.  Control proof
is then big-int AND/OR over interval cells.  This avoids judging the full JSON
graph 2**18 times while retaining exact endpoint-cell semantics.
"""
from __future__ import annotations

import itertools
from typing import Any

from .intervals import cells_between, interval_contains
from .judge import JudgeEngine, effective_coverage, is_composite_node


class FeasibilityBitset:
    def __init__(self, case: dict[str, Any], nodes: dict[str, dict[str, Any]]):
        self.case = case
        self.nodes = nodes
        self.engine = JudgeEngine(case, nodes)
        # Must match buy_best's ascending-ID bit order.
        actions = sorted(case.get("actions", []), key=lambda a: a.get("id", ""))
        self.action_ids = [a["id"] for a in actions]
        self.n = len(actions)
        if self.n > 18:
            raise ValueError("at most 18 actions are supported")
        self.mask_count = 1 << self.n
        self.universe = (1 << self.mask_count) - 1
        self.action_bits = [self._action_table(i) for i in range(self.n)]
        self.grant_index: dict[str, list[int]] = {}
        for i, action in enumerate(actions):
            grants = action.get("grants", action.get("grant", action.get("evidence_ids", [])))
            if isinstance(grants, str):
                grants = [grants]
            for eid in grants:
                self.grant_index.setdefault(eid, []).append(i)
        self._node_bits: dict[str, int] = {}
        self._stack: tuple[str, ...] = ()
        self.feasible_masks = self._compile()
        byte_len = (self.mask_count + 7) // 8
        self.feasible_bytes = self.feasible_masks.to_bytes(byte_len, "little")

    def _action_table(self, i: int) -> int:
        """Bit *m* of result is 1 iff subset mask m contains action i."""
        half = 1 << i
        chunk = ((1 << half) - 1) << half
        bits = chunk
        width = half << 1
        while width < self.mask_count:
            bits |= bits << width
            width <<= 1
        return bits

    def node_valid_bits(self, nid: str, stack: tuple[str, ...] = ()) -> int:
        if not stack and nid in self._node_bits:
            return self._node_bits[nid]
        if nid in stack:
            # Evidential cycles have no least fixed point of validity.
            return 0
        node = self.nodes.get(nid)
        if node is None:
            if not stack:
                self._node_bits[nid] = 0
            return 0

        static_bad = (
            node.get("revoked", False)
            or node.get("status") == "revoked"
            or (
                self.engine.decision_time is not None
                and isinstance(node.get("known_at", node.get("available_at")), int)
                and not isinstance(node.get("known_at", node.get("available_at")), bool)
                and node.get("known_at", node.get("available_at")) > self.engine.decision_time
            )
            or (
                not bool(node.get("prerequisites", node.get("requires", node.get("upstreams", []))))
                and str(node.get("type", "")).lower() not in ("composite", "commitment", "aggregate")
                and node.get("signed", True) is False
            )
        )
        if static_bad:
            if not stack:
                self._node_bits[nid] = 0
            return 0

        if node.get("available", True):
            bits = self.universe
        else:
            bits = 0
        for action_index in self.grant_index.get(nid, []):
            bits |= self.action_bits[action_index]

        next_stack = stack + (nid,)
        prereqs = node.get("prerequisites", node.get("requires", node.get("upstreams", [])))
        if isinstance(prereqs, str):
            prereqs = [prereqs]
        for pre in prereqs:
            if isinstance(pre, str):
                bits &= self.node_valid_bits(pre, next_stack)
                if bits == 0:
                    break
        if not stack:
            self._node_bits[nid] = bits
        return bits

    def _candidates(self, control: dict[str, Any], alt: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        independent_quorum = bool(alt.get("independent")) and max(1, int(alt.get("quorum", 1))) >= 2
        allow_composite = bool(alt.get("allow_composite_sources", False))
        for node in sorted(self.nodes.values(), key=lambda x: x.get("_order", 0)):
            if not self.engine._matches_predicate(node, alt):  # noqa: SLF001
                continue
            if independent_quorum and not allow_composite and is_composite_node(node):
                continue
            cov = effective_coverage(node, control)
            from .intervals import intersect_all_unions

            cov = intersect_all_unions(cov, control["required_intervals"])
            if cov:
                out.append({"id": node["id"], "source": node.get("source"), "coverage": cov})
        return out

    def _required_cells(
        self, control: dict[str, Any], candidates: list[dict[str, Any]]
    ) -> list[tuple[int, int]]:
        endpoints: set[int] = set()
        for a, b in control["required_intervals"]:
            endpoints.update((a, b))
        for cand in candidates:
            for a, b in cand["coverage"]:
                endpoints.update((a, b))
            for a, b in self.engine.ownership.timelines.get(cand["source"], []):
                if any(max(a, ra[0]) < min(b, ra[1]) for ra in control["required_intervals"]):
                    endpoints.update((a, b))
        cells: list[tuple[int, int]] = []
        for ra, rb in control["required_intervals"]:
            cells.extend(cells_between(ra, rb, sorted(endpoints)))
        return cells

    def _combo_cell_bits(
        self,
        combo: tuple[dict[str, Any], ...],
        at: int,
        require_independence: bool = True,
    ) -> int:
        bits = self.universe
        for cand in combo:
            if not interval_contains(cand["coverage"], at):
                return 0
            bits &= self.node_valid_bits(cand["id"])
        if len(combo) < 2 or not require_independence:
            return bits

        owners = [self.engine.ownership.owner_at(c["source"], at) for c in combo]
        if any(o is None for o in owners) or len(set(owners)) != len(owners):
            return 0
        for x, y in itertools.combinations(combo, 2):
            ok, _ = self.engine.graph_independent(x["id"], y["id"])
            if not ok:
                return 0
        return bits

    def _alternative_bits(self, control: dict[str, Any], alt: dict[str, Any]) -> int:
        candidates = self._candidates(control, alt)
        q = max(1, int(alt.get("quorum", 1)))
        cells = self._required_cells(control, candidates)
        if not cells:
            return 0

        if alt.get("stable_pair_required") and alt.get("independent") and q == 2:
            stable = 0
            for i, j in itertools.combinations(range(len(candidates)), 2):
                pair = (candidates[i], candidates[j])
                pair_bits = self.node_valid_bits(pair[0]["id"]) & self.node_valid_bits(pair[1]["id"])
                for lo, _ in cells:
                    cell_bits = self._combo_cell_bits(pair, lo)
                    if not cell_bits:
                        pair_bits = 0
                        break
                    pair_bits &= cell_bits
                    if not pair_bits:
                        break
                stable |= pair_bits
            return stable

        alt_bits = self.universe
        for lo, _ in cells:
            cell_bits = 0
            if len(candidates) >= q:
                for indices in itertools.combinations(range(len(candidates)), q):
                    combo = tuple(candidates[k] for k in indices)
                    cell_bits |= self._combo_cell_bits(
                        combo, lo, bool(alt.get("independent"))
                    )
                    if cell_bits == self.universe:
                        break
            alt_bits &= cell_bits
            if not alt_bits:
                return 0
        return alt_bits

    def _compile(self) -> int:
        feasible = self.universe
        for control in self.case["controls"]:
            alts = self.engine.alternatives(control)
            control_bits = 0
            for alt in alts:
                control_bits |= self._alternative_bits(control, alt)
                if control_bits == self.universe:
                    break
            feasible &= control_bits
            if not feasible:
                return 0
        return feasible

    def mask_is_feasible(self, mask: int) -> bool:
        return bool(self.feasible_bytes[mask >> 3] & (1 << (mask & 7)))
