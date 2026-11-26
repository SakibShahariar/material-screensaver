#!/usr/bin/env python3
"""Compare measurement medians against derived performance budgets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CHECKS = (
    ("startup_ms_median", "startup_ms", "startup ms"),
    ("cpu_percent_process_tree_median", "cpu_percent", "process-tree CPU %"),
    ("rss_end_mib_sum_median", "rss_mib", "summed RSS MiB"),
    ("gpu_render_busy_percent_median", "gpu_busy_percent", "GPU busy %"),
)


def find_violations(report: dict, budgets: dict) -> list[str]:
    violations = []
    table = budgets.get("budgets", {})
    for sample in report.get("summary_medians", []):
        key = table.get(sample["scene"], {}).get(str(sample["fps_limit"]))
        if key is None:
            continue
        for metric, budget_key, label in CHECKS:
            actual = sample.get(metric)
            limit = key.get(budget_key)
            if actual is None or limit is None:
                continue
            if actual > limit:
                violations.append(
                    f"{sample['scene']} at {sample['fps_label']}: {label} "
                    f"{actual} exceeds budget {limit}")
    return violations


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--budgets", type=Path, required=True)
    parser.add_argument("--warn-only", action="store_true",
                        help="report violations but always exit 0")
    args = parser.parse_args(argv)
    report = json.loads(args.metrics.read_text(encoding="utf-8"))
    budgets = json.loads(args.budgets.read_text(encoding="utf-8"))
    violations = find_violations(report, budgets)
    if not violations:
        print(f"Performance budgets OK ({budgets.get('profile', 'unknown')} profile)")
        return 0
    for line in violations:
        print(f"WARNING: {line}")
    if args.warn_only:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
