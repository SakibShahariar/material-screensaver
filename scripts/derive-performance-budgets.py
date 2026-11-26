#!/usr/bin/env python3
"""Derive performance budgets from a repeated-samples metrics report.

Budget rule: 1.5x the worst observed sample for CPU/GPU/startup, 1.3x for summed
RSS, rounded outward. GPU busy is capped at 100%. These are thresholds for
detecting regressions, not guarantees of performance on other hardware.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def derive(report: dict) -> dict:
    groups = {}
    for sample in report["samples"]:
        groups.setdefault((sample["scene"], sample["fps_limit"]), []).append(sample)
    budgets = {}
    for (scene, fps), values in sorted(groups.items()):
        def worst(key):
            present = [value[key] for value in values if value.get(key) is not None]
            return max(present) if present else None

        entry = {
            "startup_ms": math.ceil(worst("startup_ms_to_load_finished") * 1.5 / 50) * 50,
            "cpu_percent": math.ceil(worst("cpu_percent_process_tree") * 1.5),
            "rss_mib": math.ceil(worst("rss_end_mib_sum") * 1.3 / 10) * 10,
        }
        gpu = worst("gpu_render_busy_percent_median")
        if gpu is not None:
            entry["gpu_busy_percent"] = min(100, math.ceil(gpu * 1.5))
        budgets.setdefault(scene, {})[str(fps)] = entry
    return budgets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--profile", required=True,
                        help="profile name recorded in the output JSON")
    parser.add_argument("--source", required=True, help="human-readable source description")
    args = parser.parse_args(argv)
    report = json.loads(args.metrics.read_text(encoding="utf-8"))
    output = {
        "profile": args.profile,
        "source": args.source,
        "method": "1.5x worst sample for CPU/GPU/startup, 1.3x for summed RSS; GPU capped at 100%",
        "budgets": derive(report),
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
