"""Generate the 32-control reuse/pricing synthetic fixture.

Run from repository root:
    python fixtures/06_bundle_reuse/generate_fixture.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

control_count = 32
controls = []
for i in range(1, control_count + 1):
    cid = f"C_{i:02d}"
    controls.append(
        {
            "id": cid,
            "risk_class": "shared-control-reuse",
            "required_intervals": [[100, 900]],
            "required_regions": ["CN"],
            "rule": {
                "alternatives": [
                    {"id": "annual_or_shared_report", "kinds": ["annual_report"]},
                    {
                        "id": "two_independent_labs",
                        "kinds": ["lab_report"],
                        "quorum": 2,
                        "independent": True,
                        "coverage_policy": "at_each_time",
                    },
                ]
            },
        }
    )

case = {
    "schema": "proofmarket.case.v1",
    "case_id": "06_bundle_tier_and_reuse_32_controls",
    "horizon": [0, 1000],
    "controls": controls,
    "ownership_intervals": [
        {"entity": "BATCH_LAB_A", "owner": "BATCH_OWNER_A", "start": 0, "end": 1000},
        {"entity": "BATCH_LAB_B", "owner": "BATCH_OWNER_B", "start": 0, "end": 1000},
        {"entity": "BATCH_LAB_C", "owner": "BATCH_OWNER_C", "start": 0, "end": 1000},
    ],
    "pricing_batches": [
        {
            "id": "lab_batch",
            "count_basis": "action",
            "tiers": [
                {"min_count": 1, "max_count": 2, "unit_cost": 6},
                {"min_count": 3, "max_count": 18, "unit_cost": 4},
            ],
        }
    ],
    "actions": [
        {
            "id": "act_broad_shared_report",
            "grants": ["E_BROAD_SHARED"],
            "full_period_cost": 10,
            "review_days": 2,
            "line_count": 1,
        },
        {
            "id": "act_cheap_but_quoted_universal",
            "grants": ["E_NARROW_ACTUAL"],
            "full_period_cost": 1,
            "review_days": 1,
            "quoted_controls": "*",
            "quoted_regions": ["*"],
            "quoted_intervals": [[0, 1000]],
            "quote_would_claim": "Quotation scope is deliberately broader than true coverage.",
        },
        {"id": "act_lab_a", "grants": ["E_LAB_A"], "batch": "lab_batch", "review_days": 1},
        {"id": "act_lab_b", "grants": ["E_LAB_B"], "batch": "lab_batch", "review_days": 1},
        {"id": "act_lab_c", "grants": ["E_LAB_C"], "batch": "lab_batch", "review_days": 1},
    ],
}

evidence = {
    "schema": "proofmarket.evidence.v1",
    "nodes": [
        {
            "id": "E_BROAD_SHARED",
            "kind": "annual_report",
            "type": "leaf",
            "available": False,
            "signed": True,
            "source": "SHARED_AUDITOR",
            "approved_regions": ["CN"],
            "coverage": [
                {"controls": "*", "regions": ["CN"], "intervals": [[100, 900]]}
            ],
            "reuse_note": "One real coverage claim is reused by all 32 controls.",
        },
        {
            "id": "E_NARROW_ACTUAL",
            "kind": "annual_report",
            "type": "leaf",
            "available": False,
            "signed": True,
            "approved_regions": ["CN"],
            "coverage": [
                {"controls": ["C_01"], "regions": ["CN"], "intervals": [[100, 900]]}
            ],
        },
        *[
            {
                "id": f"E_LAB_{suffix}",
                "kind": "lab_report",
                "type": "leaf",
                "available": False,
                "source": f"BATCH_LAB_{suffix}",
                "approved_regions": ["CN"],
                "coverage": [
                    {"controls": "*", "regions": ["CN"], "intervals": [[100, 900]]}
                ],
            }
            for suffix in ("A", "B", "C")
        ],
    ],
}

(HERE / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(HERE / "evidence.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(f"wrote {control_count} controls to {HERE}")
