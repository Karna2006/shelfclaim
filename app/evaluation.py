"""Produce evidence-bounded evaluation summaries from packet and GT files.

Input: saved claim packet and ground-truth CSVs. Output: one Markdown report;
metrics are reported as unmeasured when required evidence is absent.
"""

from __future__ import annotations

import csv
from pathlib import Path

_BARS = (
    ("Book count error", "≤ 5%"),
    ("Title ID accuracy", "≥ 70%"),
    ("Confidently wrong", "≤ 3%"),
    ("Spine dimensions", "17/20 within 15%"),
    ("Book prices", "12/15 within 25%; median ≤ 25%"),
    ("Non-book items", "≥ 80% correct category"),
    ("Floor area", "≤ 10%"),
    ("Wall area", "≤ 15%"),
    ("Time to packet", "< 5 min"),
)


def evaluate_sweep(sweep: Path, gt_dir: Path, output: Path) -> Path:
    """Write actual metrics only when packet and nonempty GT measurements exist."""
    packet = sweep / "claim_packet.json"
    count_gt = gt_dir / "count_gt.csv"
    complete_rows = []
    if count_gt.is_file():
        with count_gt.open(encoding="utf-8", newline="") as source:
            complete_rows = [
                row for row in csv.DictReader(source) if row.get("true_count", "").strip()
            ]
    if not packet.is_file() or not complete_rows:
        reasons = []
        if not packet.is_file():
            reasons.append("claim_packet.json is missing")
        if not complete_rows:
            reasons.append("count_gt.csv has no measured true_count rows")
        rows = "\n".join(
            f"| {name} | {target} | NOT MEASURED | {', '.join(reasons)} |" for name, target in _BARS
        )
        content = (
            f"# Evaluation — {sweep.name}\n\n"
            "Status: **BLOCKED**. The required packet and/or ground truth is unavailable; "
            "no accuracy values are inferred.\n\n"
            "| Metric | Pass bar | Result | Evidence |\n|---|---:|---|---|\n"
            f"{rows}\n\nRoom area is not measured because 3D reconstruction is out of scope.\n"
        )
    else:
        content = (
            f"# Evaluation — {sweep.name}\n\n"
            "Status: **BLOCKED**. The packet and count ground truth exist, but this evaluator "
            "does not yet compute the complete matching metrics. No partial score is reported.\n"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return output
