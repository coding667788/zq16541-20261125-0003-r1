"""Exhaustive procurement planning over at most 18 actions."""
from __future__ import annotations

from typing import Any

from .intervals import InputError
from .judge import JudgeEngine
from .feasibility import FeasibilityBitset
from .loader import load_case, load_evidence


def _number(value: Any, path: str, default: float | int = 0) -> float | int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{path} must be a number")
    if value < 0:
        raise InputError(f"{path} must be non-negative")
    return value


def action_by_id(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i, action in enumerate(case.get("actions", [])):
        if not isinstance(action, dict):
            raise InputError(f"actions[{i}] must be an object")
        aid = action.get("id")
        if not isinstance(aid, str) or not aid:
            raise InputError(f"actions[{i}].id must be a non-empty string")
        if aid in out:
            raise InputError(f"duplicate action id {aid!r}")
        action.setdefault("grants", action.get("grant", action.get("evidence_ids", [])))
        if isinstance(action["grants"], str):
            action["grants"] = [action["grants"]]
        out[aid] = action
    return out


def batch_by_id(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for i, batch in enumerate(case.get("pricing_batches", [])):
        if not isinstance(batch, dict):
            raise InputError(f"pricing_batches[{i}] must be an object")
        bid = batch.get("id", batch.get("batch_id"))
        if not isinstance(bid, str) or not bid:
            raise InputError(f"pricing_batches[{i}].id must be a string")
        out[bid] = batch
    return out


def _tier_for_count(batch: dict[str, Any], count: int) -> dict[str, Any] | None:
    tiers = batch.get("tiers", batch.get("price_tiers", []))
    if not isinstance(tiers, list):
        raise InputError(f"batch {batch.get('id')!r}.tiers must be a list")
    chosen = None
    chosen_min = -1
    for i, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            raise InputError(f"batch {batch.get('id')!r}.tiers[{i}] must be an object")
        minimum = tier.get("min", tier.get("min_count", tier.get("min_actions", 1)))
        maximum = tier.get("max", tier.get("max_count", tier.get("max_actions")))
        if not isinstance(minimum, int) or (maximum is not None and not isinstance(maximum, int)):
            raise InputError(f"batch {batch.get('id')!r} tier bounds must be integers")
        if count < minimum:
            continue
        if maximum is not None and count > maximum:
            continue
        if minimum > chosen_min:
            chosen = tier
            chosen_min = minimum
    return chosen


def batch_cost_for_count(batch: dict[str, Any], count: int) -> float | int:
    if count == 0:
        return 0
    tier = _tier_for_count(batch, count)
    if tier is None:
        raise InputError(f"no price tier in batch {batch.get('id')!r} matches count {count}")
    if "total_cost" in tier or "package_cost" in tier:
        return _number(tier.get("total_cost", tier.get("package_cost")), f"batches.{batch.get('id')}.total_cost")
    if "unit_cost" in tier or "each_cost" in tier or "per_action_cost" in tier:
        unit = _number(
            tier.get("unit_cost", tier.get("each_cost", tier.get("per_action_cost"))),
            f"batches.{batch.get('id')}.unit_cost",
        )
        return unit * count
    cost = _number(tier.get("cost", tier.get("price", 0)), f"batches.{batch.get('id')}.cost")
    if str(batch.get("cost_mode", "unit")) == "unit":
        return cost * count
    return cost


def price_selection(
    case: dict[str, Any], selected_ids: list[str] | set[str] | tuple[str, ...]
) -> dict[str, Any]:
    actions = action_by_id(case)
    batches = batch_by_id(case)
    unknown = [aid for aid in selected_ids if aid not in actions]
    if unknown:
        raise InputError(f"unknown purchase action ids: {unknown}")
    selected = [actions[aid] for aid in selected_ids]

    review_days: float | int = 0
    line_count = 0
    action_count = len(selected)
    for a in selected:
        review_days += _number(
            a.get("review_days", a.get("manual_review_days", a.get("review", 0))),
            f"actions.{a['id']}.review_days",
            0,
        )
        line_count += int(a.get("line_count", a.get("quantity", 1)))

    batch_counts: dict[str, int] = {}
    batch_line_counts: dict[str, int] = {}
    batch_evidence_counts: dict[str, set[str]] = {}
    individual_cost: float | int = 0
    breakdown: dict[str, Any] = {"individual_actions": [], "batches": {}}

    for a in selected:
        bid = a.get("batch", a.get("pricing_batch", a.get("price_batch")))
        if bid is None:
            cost = _number(a.get("full_period_cost", a.get("cost", a.get("price", 0))), f"actions.{a['id']}.cost")
            individual_cost += cost
            breakdown["individual_actions"].append({"id": a["id"], "cost": cost})
        else:
            if bid not in batches:
                raise InputError(f"action {a['id']!r} references unknown pricing batch {bid!r}")
            batch_counts[bid] = batch_counts.get(bid, 0) + 1
            batch_line_counts[bid] = batch_line_counts.get(bid, 0) + int(a.get("line_count", 1))
            batch_evidence_counts.setdefault(bid, set()).update(a.get("grants", []))

    total_cost: float | int = individual_cost
    for bid, count_actions in batch_counts.items():
        batch = batches[bid]
        basis = batch.get("count_basis", "action")
        if basis in ("line", "line_count", "purchase_count"):
            count = batch_line_counts[bid]
        elif basis in ("evidence", "evidence_count", "granted_evidence"):
            count = len(batch_evidence_counts[bid])
        else:
            count = count_actions
        tier = _tier_for_count(batch, count)
        if tier is None:
            raise InputError(f"no price tier in batch {bid!r} matches count {count}")
        cost = batch_cost_for_count(batch, count)
        if "total_cost" in tier or "package_cost" in tier:
            mode = "total"
        elif "unit_cost" in tier or "each_cost" in tier or "per_action_cost" in tier:
            mode = "unit"
        else:
            mode = str(batch.get("cost_mode", "unit"))
        total_cost += cost
        breakdown["batches"][bid] = {
            "count_basis": basis,
            "count": count,
            "tier_min": tier.get("min", tier.get("min_count", tier.get("min_actions", 1))),
            "cost_mode": mode,
            "cost": cost,
            "selected_actions": sorted(
                a["id"] for a in selected if a.get("batch", a.get("pricing_batch")) == bid
            ),
        }

    return {
        "full_period_cost": total_cost,
        "review_days": review_days,
        "purchase_count": line_count,
        "action_count": action_count,
        "breakdown": breakdown,
    }


def granted_evidence(case: dict[str, Any], selected_ids: list[str]) -> set[str]:
    actions = action_by_id(case)
    granted: set[str] = set()
    for aid in selected_ids:
        granted.update(actions[aid].get("grants", []))
    return granted


def buy_best(
    case: dict[str, Any] | str,
    evidence: dict[str, dict[str, Any]] | str | None = None,
    *,
    max_actions: int = 18,
    include_judgement: bool = True,
) -> dict[str, Any]:
    if isinstance(case, str):
        case = load_case(case)
    else:
        case = load_case(case)
    if evidence is None:
        nodes = load_evidence(case.get("evidence", case.get("evidence_nodes", {})))
    elif isinstance(evidence, str):
        nodes = load_evidence(evidence)
    else:
        nodes = evidence

    actions = action_by_id(case)
    # Sort so bit-index order is also the final ascending-ID tie-break order.
    action_ids = sorted(actions)
    n = len(action_ids)
    if n > 18:
        raise InputError("proofmarket buy supports at most 18 candidate purchase actions")
    if max_actions > 18:
        raise InputError("max_actions may not exceed the hard limit of 18")

    mask_count = 1 << n
    days_table = [0] * mask_count
    line_table = [0] * mask_count
    simple_cost_table = [0] * mask_count
    review_values = []
    line_values = []
    simple_values = []
    for aid in action_ids:
        action = actions[aid]
        review_values.append(
            _number(action.get("review_days", action.get("manual_review_days", action.get("review", 0))),
                    f"actions.{aid}.review_days")
        )
        line_values.append(int(action.get("line_count", action.get("quantity", 1))))
        bid = action.get("batch", action.get("pricing_batch", action.get("price_batch")))
        if bid is None:
            simple_values.append(
                _number(action.get("full_period_cost", action.get("cost", action.get("price", 0))),
                        f"actions.{aid}.cost")
            )
        else:
            simple_values.append(0)

    batches = batch_by_id(case)
    fast_batches = []
    complex_batch_pricing = False
    batch_masks: dict[str, int] = {}
    for i, aid in enumerate(action_ids):
        bid = actions[aid].get("batch", actions[aid].get("pricing_batch", actions[aid].get("price_batch")))
        if bid is not None:
            batch_masks[bid] = batch_masks.get(bid, 0) | (1 << i)
    for bid, batch_mask in batch_masks.items():
        batch = batches[bid]
        basis = batch.get("count_basis", "action")
        if basis not in ("action", "actions"):
            complex_batch_pricing = True
            continue
        costs = [batch_cost_for_count(batch, c) for c in range(n + 1)]
        fast_batches.append((batch_mask, costs))

    for mask in range(1, mask_count):
        bit = mask & -mask
        i = bit.bit_length() - 1
        previous = mask ^ bit
        days_table[mask] = days_table[previous] + review_values[i]
        line_table[mask] = line_table[previous] + line_values[i]
        simple_cost_table[mask] = simple_cost_table[previous] + simple_values[i]

    engine = JudgeEngine(case, nodes)
    compiler = FeasibilityBitset(case, nodes)
    best_key = None
    best_mask = None
    feasible_plans = 0
    considered = 0

    for mask in range(mask_count):
        count = mask.bit_count()
        if count > max_actions:
            continue
        considered += 1
        if not compiler.mask_is_feasible(mask):
            continue
        feasible_plans += 1
        ids = [action_ids[i] for i in range(n) if mask & (1 << i)]
        if complex_batch_pricing:
            metrics = price_selection(case, ids)
            cost = metrics["full_period_cost"]
            review_days = metrics["review_days"]
            purchase_count = metrics["purchase_count"]
        else:
            cost = simple_cost_table[mask]
            for batch_mask, costs in fast_batches:
                cost += costs[(mask & batch_mask).bit_count()]
            review_days = days_table[mask]
            purchase_count = line_table[mask]
        key = (cost, review_days, purchase_count, tuple(ids))
        if best_key is None or key < best_key:
            best_key = key
            best_mask = mask

    best_ids = (
        [action_ids[i] for i in range(n) if best_mask & (1 << i)]
        if best_mask is not None
        else None
    )
    best_metrics = price_selection(case, best_ids) if best_ids is not None else None
    best_judgement = engine.judge(granted_evidence(case, best_ids)) if best_ids is not None and include_judgement else None

    if best_ids is None:
        all_ids = action_ids
        all_granted = granted_evidence(case, all_ids)
        worst = engine.judge(all_granted)
        return {
            "schema": "proofmarket.plan.v1",
            "case_id": case.get("case_id"),
            "feasible": False,
            "unique": False,
            "max_actions": max_actions,
            "enumeration": {
                "candidate_actions": n,
                "subsets_considered": considered,
                "feasible_plans": 0,
            },
            "all_actions_judgement": worst,
            "reason": "no subset of purchase actions proves every control",
        }

    result = {
        "schema": "proofmarket.plan.v1",
        "case_id": case.get("case_id"),
        "feasible": True,
        "unique": True,
        "max_actions": max_actions,
        "selected_actions": best_ids,
        "selected_ids": best_ids,
        "granted_evidence": sorted(granted_evidence(case, best_ids)),
        "full_period_cost": best_metrics["full_period_cost"],
        "review_days": best_metrics["review_days"],
        "purchase_count": best_metrics["purchase_count"],
        "metrics": best_metrics,
        "objective_order": [
            "full_period_cost",
            "subsequent_manual_review_days",
            "purchase_count",
            "ascending_action_ids",
        ],
        "tie_break_key": list(best_key[:3]) + [list(best_key[3])],
        "enumeration": {
            "candidate_actions": n,
            "subsets_considered": considered,
            "feasible_plans": feasible_plans,
        },
    }
    if include_judgement:
        result["judgement"] = best_judgement
    return result
