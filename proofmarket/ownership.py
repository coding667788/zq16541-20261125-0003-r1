"""Actual-ownership interval calculations."""
from __future__ import annotations

from bisect import bisect_right
from typing import Any

from .intervals import InputError, Interval, normalize, parse_intervals


class OwnershipIndex:
    def __init__(self, records: list[dict[str, Any]]):
        self.timelines: dict[str, list[Interval]] = {}
        self.owners: dict[str, list[str]] = {}
        grouped: dict[str, list[tuple[Interval, str]]] = {}
        for i, rec in enumerate(records):
            if not isinstance(rec, dict):
                raise InputError(f"ownership_intervals[{i}] must be an object")
            entity = rec.get("entity", rec.get("lab", rec.get("source", rec.get("id"))))
            owner = rec.get("owner", rec.get("ultimate_owner", rec.get("parent")))
            if not isinstance(entity, str) or not entity:
                raise InputError(f"ownership_intervals[{i}].entity must be a non-empty string")
            if not isinstance(owner, str) or not owner:
                raise InputError(f"ownership_intervals[{i}].owner must be a non-empty string")
            if "intervals" in rec:
                ivs = parse_intervals(rec["intervals"], f"ownership_intervals[{i}].intervals")
            else:
                ivs = parse_intervals(
                    [[rec.get("start", rec.get("from")), rec.get("end", rec.get("to"))]],
                    f"ownership_intervals[{i}]",
                )
            grouped.setdefault(entity, []).extend((iv, owner) for iv in ivs)

        for entity, entries in grouped.items():
            entries.sort(key=lambda x: (x[0][0], x[0][1], x[1]))
            ivs: list[Interval] = []
            owners: list[str] = []
            for iv, owner in entries:
                # Exact overlapping ownership disputes are rejected rather than
                # silently choosing one parent.  Adjacent records are fine.
                if ivs and iv[0] < ivs[-1][1] and owner != owners[-1]:
                    raise InputError(
                        f"conflicting overlapping ownership for {entity!r}: "
                        f"{owners[-1]} and {owner} near {iv[0]}"
                    )
                if ivs and iv[0] <= ivs[-1][1] and owner == owners[-1]:
                    old = ivs[-1]
                    ivs[-1] = (old[0], max(old[1], iv[1]))
                else:
                    ivs.append(iv)
                    owners.append(owner)
            # Do not use interval normalization here: adjacent records can have
            # different owners and must remain separate timeline segments.
            self.timelines[entity] = ivs
            self.owners[entity] = owners

    def owner_at(self, entity: str | None, at: int) -> str | None:
        if not entity:
            return None
        ivs = self.timelines.get(entity)
        if not ivs:
            return None
        starts = [a for a, _ in ivs]
        idx = bisect_right(starts, at) - 1
        if idx < 0:
            return None
        a, b = ivs[idx]
        if a <= at < b:
            return self.owners[entity][idx]
        return None

    def independence_cells(
        self, source_a: str | None, source_b: str | None, cells: list[Interval]
    ) -> list[tuple[Interval, bool, str | None, str | None]]:
        out = []
        for lo, hi in cells:
            owner_a = self.owner_at(source_a, lo)
            owner_b = self.owner_at(source_b, lo)
            independent = (
                source_a is not None
                and source_b is not None
                and source_a != source_b
                and owner_a is not None
                and owner_b is not None
                and owner_a != owner_b
            )
            out.append(((lo, hi), independent, owner_a, owner_b))
        return out

    def common_owner_intervals(
        self, source_a: str, source_b: str, span: list[Interval]
    ) -> list[Interval]:
        """Exact intervals in span where two sources have the same known owner."""
        endpoints = set()
        for iv in span:
            endpoints.update(iv)
        for entity in (source_a, source_b):
            for a, b in self.timelines.get(entity, []):
                for iv in span:
                    lo = max(a, iv[0])
                    hi = min(b, iv[1])
                    if lo < hi:
                        endpoints.add(lo)
                        endpoints.add(hi)
        points = sorted(endpoints)
        result: list[Interval] = []
        for x, y in zip(points, points[1:]):
            if any(lo <= x < hi for lo, hi in span):
                oa = self.owner_at(source_a, x)
                ob = self.owner_at(source_b, x)
                if oa is not None and oa == ob:
                    result.append((x, y))
        return normalize(result)
