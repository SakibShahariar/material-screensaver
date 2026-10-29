#!/usr/bin/env python3
"""Enforce a conservative source-payload budget for built-in HTML scenes.

This is a deterministic CI guard for accidental oversized scene payloads. It is
not a substitute for runtime CPU/GPU/memory profiling in a graphical session.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCENE_DIR = ROOT / "screensavers"
MAX_SCENE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 512 * 1024


def main() -> int:
    scenes = sorted(SCENE_DIR.glob("*.html"))
    if not scenes:
        print(f"error: no scene HTML files found in {SCENE_DIR}", file=sys.stderr)
        return 2

    sizes = [(scene, scene.stat().st_size) for scene in scenes]
    total = sum(size for _, size in sizes)
    failures = []
    for scene, size in sizes:
        status = "OK" if size <= MAX_SCENE_BYTES else "OVER BUDGET"
        print(f"{status:12} {size:7} bytes  {scene.name}")
        if size > MAX_SCENE_BYTES:
            failures.append(f"{scene.name} is {size} bytes (limit {MAX_SCENE_BYTES})")

    print(f"Total scene source: {total} bytes (limit {MAX_TOTAL_BYTES} bytes)")
    if total > MAX_TOTAL_BYTES:
        failures.append(f"combined scene source is {total} bytes (limit {MAX_TOTAL_BYTES})")
    if failures:
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return 1
    print(f"Scene payload budget passed for {len(scenes)} scene(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
