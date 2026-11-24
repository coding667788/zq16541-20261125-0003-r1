"""Exact half-open integer interval helpers.

All time coordinates are Python integers.  The host axis may have span 10**9;
these routines touch only supplied endpoints and never iterate time points.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from typing import Any

Interval = tuple[int, int]


class InputError(ValueError):
    """Raised when a JSON document does not satisfy the documented format."""


def as_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"{path} must be an integer, got {type(value).__name__}")
    return value


def parse_interval(value: Any, path: str = "interval") -> Interval:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) != 2:
            raise InputError(f"{path} must contain exactly two endpoints")
        start = as_int(value[0], f"{path}[0]")
        end = as_int(value[1], f"{path}[1]")
    elif isinstance(value, dict):
        start = None
        end = None
        for key in ("start", "lo", "from", "begin", "left"):
            if key in value:
                start = as_int(value[key], f"{path}.{key}")
                break
        for key in ("end", "hi", "to", "until", "right"):
            if key in value:
                end = as_int(value[key], f"{path}.{key}")
                break
        if start is None or end is None:
            raise InputError(f"{path} needs start/end endpoints")
    else:
        raise InputError(f"{path} must be [start,end] or an endpoint object")
    if start > end:
        raise InputError(f"{path} has start {start} after end {end}")
    return start, end


def parse_intervals(value: Any, path: str = "intervals") -> list[Interval]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InputError(f"{path} must be a list of half-open intervals")
    out: list[Interval] = []
    for i, item in enumerate(value):
        iv = parse_interval(item, f"{path}[{i}]")
        if iv[0] < iv[1]:
            out.append(iv)
    return normalize(out)


def normalize(intervals: Iterable[Interval]) -> list[Interval]:
    ordered = sorted((a, b) for a, b in intervals if a < b)
    merged: list[Interval] = []
    for a, b in ordered:
        if not merged or a > merged[-1][1]:
            merged.append((a, b))
        elif b > merged[-1][1]:
            # Overlap or half-open adjacency.
            merged[-1] = (merged[-1][0], b)
    return merged


def union_all(intervals: Iterable[Interval]) -> list[Interval]:
    return normalize(list(intervals))


def intersect_pair(a: Interval, b: Interval) -> Interval | None:
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    return (lo, hi) if lo < hi else None


def intersect_all_unions(left: Sequence[Interval], right: Sequence[Interval]) -> list[Interval]:
    """Intersect two normalized interval unions in O(m+n)."""
    i = j = 0
    out: list[Interval] = []
    while i < len(left) and j < len(right):
        iv = intersect_pair(left[i], right[j])
        if iv is not None:
            out.append(iv)
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return normalize(out)


def intersect_many(unions: Iterable[Sequence[Interval]]) -> list[Interval]:
    result: list[Interval] | None = None
    for union in unions:
        result = list(union) if result is None else intersect_all_unions(result, union)
        if not result:
            return []
    return result or []


def subtract_union(source: Sequence[Interval], removed: Sequence[Interval]) -> list[Interval]:
    """Return normalized source minus normalized removed."""
    out: list[Interval] = []
    j = 0
    rem = normalize(removed)
    for a, b in normalize(source):
        cur = a
        while j < len(rem) and rem[j][1] <= cur:
            j += 1
        k = j
        while k < len(rem) and rem[k][0] < b:
            rlo, rhi = rem[k]
            if rlo > cur:
                out.append((cur, min(rlo, b)))
            cur = max(cur, rhi)
            if cur >= b:
                break
            k += 1
        if cur < b:
            out.append((cur, b))
    return normalize(out)


def contains_union(whole: Sequence[Interval], part: Sequence[Interval]) -> bool:
    """Whether ``part`` covers every point of ``whole`` (extra part is allowed)."""
    return not subtract_union(whole, part)


def first_gap(required: Sequence[Interval], covered: Sequence[Interval]) -> Interval | None:
    gaps = subtract_union(required, covered)
    return gaps[0] if gaps else None


def all_endpoints(*unions: Sequence[Interval]) -> list[int]:
    points: set[int] = set()
    for union in unions:
        for a, b in union:
            points.add(a)
            points.add(b)
    return sorted(points)


def cells_between(lo: int, hi: int, endpoints: Iterable[int]) -> list[Interval]:
    """Return non-empty half-open cells inside [lo,hi), split at endpoints."""
    points = {lo, hi}
    for p in endpoints:
        if lo < p < hi:
            points.add(p)
    ordered = sorted(points)
    return [(a, b) for a, b in zip(ordered, ordered[1:]) if a < b]


def cells_of_unions(*unions: Sequence[Interval]) -> list[Interval]:
    """Elementary cells covering the bounding range of supplied unions."""
    normalized = [normalize(u) for u in unions]
    flat = [iv for u in normalized for iv in u]
    if not flat:
        return []
    lo = min(a for a, _ in flat)
    hi = max(b for _, b in flat)
    return cells_between(lo, hi, all_endpoints(*normalized))


def interval_contains(union: Sequence[Interval], point: int) -> bool:
    for a, b in union:
        if a <= point < b:
            return True
        if a > point:
            return False
    return False


def interval_at(union: Sequence[Interval], point: int) -> Interval | None:
    idx = bisect_right([a for a, _ in union], point) - 1
    if idx >= 0 and union[idx][0] <= point < union[idx][1]:
        return union[idx]
    return None


def to_json(union: Sequence[Interval]) -> list[list[int]]:
    return [[a, b] for a, b in normalize(union)]
