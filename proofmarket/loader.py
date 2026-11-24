"""JSON loading and light schema validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .intervals import InputError, parse_intervals


def read_json(path: str | Path) -> Any:
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise InputError(f"cannot read {p}: {exc}") from exc
    def reject_constant(value: str) -> None:
        raise InputError(f"non-standard JSON constant {value!r} is not allowed")

    try:
        return json.loads(raw, parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid UTF-8 JSON in {p}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc


def load_case(path: str | Path | dict[str, Any]) -> dict[str, Any]:
    data = path if isinstance(path, dict) else read_json(path)
    if not isinstance(data, dict):
        raise InputError("CASE must be a JSON object")
    controls = data.get("controls")
    if not isinstance(controls, list) or not controls:
        raise InputError("CASE.controls must be a non-empty list")
    ids: set[str] = set()
    for i, c in enumerate(controls):
        if not isinstance(c, dict):
            raise InputError(f"controls[{i}] must be an object")
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            raise InputError(f"controls[{i}].id must be a non-empty string")
        if cid in ids:
            raise InputError(f"duplicate control id {cid!r}")
        ids.add(cid)
        req = c.get("required_intervals", c.get("required", c.get("intervals")))
        c["required_intervals"] = parse_intervals(req, f"controls[{i}].required_intervals")
        if not c["required_intervals"]:
            raise InputError(f"control {cid!r} needs a non-empty required interval union")
        regions = c.get("required_regions", c.get("regions", ["*"]))
        if isinstance(regions, str):
            regions = [regions]
        if not isinstance(regions, list) or not all(isinstance(r, str) for r in regions):
            raise InputError(f"control {cid!r}.required_regions must be a string or string list")
        c["required_regions"] = regions or ["*"]
        c.setdefault("rule", c.get("proof") or {})
    data.setdefault("ownership_intervals", [])
    if not isinstance(data["ownership_intervals"], list):
        raise InputError("CASE.ownership_intervals must be a list")
    data.setdefault("actions", [])
    if not isinstance(data["actions"], list):
        raise InputError("CASE.actions must be a list")
    if len(data["actions"]) > 18:
        raise InputError("proofmarket buy supports at most 18 purchase actions")
    data.setdefault("pricing_batches", data.get("batches", []))
    if not isinstance(data["pricing_batches"], list):
        raise InputError("CASE.pricing_batches must be a list")
    return data


def _nodes_from_evidence_data(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("nodes", "evidence", "items", "records"):
            if key in data:
                nodes = data[key]
                if isinstance(nodes, dict):
                    # Allow {"E1": {...}} maps.
                    out = []
                    for nid, node in nodes.items():
                        if not isinstance(node, dict):
                            raise InputError(f"evidence.{nid} must be an object")
                        node = dict(node)
                        node.setdefault("id", nid)
                        out.append(node)
                    return out
                if isinstance(nodes, list):
                    return nodes
        if "id" in data:
            return [data]
        if data and all(isinstance(v, dict) for v in data.values()):
            out = []
            for nid, node in data.items():
                node = dict(node)
                node.setdefault("id", nid)
                out.append(node)
            return out
    raise InputError("EVIDENCE must be a list, an object with nodes/evidence, an id map, or one node")


def load_evidence(path: str | Path | dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    data = path if isinstance(path, (dict, list)) else read_json(path)
    raw_nodes = _nodes_from_evidence_data(data)
    nodes: dict[str, dict[str, Any]] = {}
    for i, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            raise InputError(f"evidence nodes[{i}] must be an object")
        nid = node.get("id")
        if not isinstance(nid, str) or not nid:
            raise InputError(f"evidence nodes[{i}].id must be a non-empty string")
        if nid in nodes:
            raise InputError(f"duplicate evidence id {nid!r}")
        node = dict(node)
        node["_order"] = i
        node.setdefault("available", True)
        node.setdefault("prerequisites", node.get("requires", node.get("upstreams", [])))
        if isinstance(node["prerequisites"], str):
            node["prerequisites"] = [node["prerequisites"]]
        if not isinstance(node["prerequisites"], list):
            raise InputError(f"evidence {nid!r}.prerequisites must be a list of ids")
        node.setdefault("kind", node.get("type", "evidence"))
        node.setdefault("source", node.get("lab", node.get("source_id")))
        nodes[nid] = node
    return nodes
