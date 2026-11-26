#!/usr/bin/env python3
"""Collect CPU/RSS/GPU samples for scenes on real GNOME hardware.

Unlike ``measure-scene-performance.py`` (Xvfb, software rendering), this script
runs the viewer on the current desktop and samples ``intel_gpu_top`` alongside
the viewer process tree. It is a baseline collector, not a pass/fail gate.

Usage (Intel integrated GPU)::

  doas -n true   # confirm passwordless doas first
  python3 scripts/measure-hardware-performance.py --fps 30,15 --repeat 3 \\
      --duration 4 --warmup 1 --output hardware-performance.json
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

spec = importlib.util.spec_from_file_location(
    "scene_performance_baseline", ROOT / "scripts" / "measure-scene-performance.py")
measure = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = measure
spec.loader.exec_module(measure)

GPU_COMMAND = ["doas", "intel_gpu_top", "-J", "-s", "200"]


def _gpu_busy_values(text: str) -> list[float]:
    """Extract Render/3D busy percentages from consecutive JSON documents."""
    decoder = json.JSONDecoder()
    values = []
    index = 0
    while index < len(text):
        while index < len(text) and not text[index].lstrip().startswith("{"):
            index += 1
        if index >= len(text):
            break
        try:
            document, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        index = end
        engine = (document.get("engines") or {}).get("Render/3D") or {}
        if isinstance(engine.get("busy"), (int, float)):
            values.append(float(engine["busy"]))
    return values


def _median_or_none(values):
    return round(statistics.median(values), 2) if values else None


def _renderer_string() -> str:
    try:
        output = subprocess.run(["glxinfo", "-B"], capture_output=True, text=True,
                                timeout=3, check=False).stdout
        for line in output.splitlines():
            if "OpenGL renderer string:" in line:
                return line.split(":", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _measure_one(ctl, Gtk, GLib, WebKit, scene_path: Path, fps: int,
                 warmup: int, duration: int, gpu_path: Path):
    config = dict(ctl.DEFAULT_CONFIG)
    native = fps == 0
    config.update({
        "fps_limit": 60 if native else fps,
        "fps_cap_disabled": native,
        "reduce_fps_on_battery": False,
        "lock_after_seconds": 0,
        "lock_countdown": False,
        "clock_overlay": False,
        "blank_display_after_minutes": 0,
    })
    ctl._is_showing = False
    ctl._viewer_windows = []
    started = time.perf_counter()
    windows = ctl._create_viewer_windows(str(scene_path), viewer_cfg=config)
    ctl._viewer_windows = windows
    ctl._is_showing = True
    views = measure._webviews_from_windows(windows)
    loop = GLib.MainLoop()
    state = {"loaded": False, "startup_ms": None, "before": None, "after": None,
             "elapsed": None, "timed_out": False}
    gpu_process = None
    timeout_id = None

    def finish_sample():
        if timeout_id is not None:
            try:
                GLib.source_remove(timeout_id)
            except Exception:
                pass
        if gpu_process is not None:
            try:
                gpu_process.terminate()
                gpu_process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
        state["after"] = measure._sample_process_tree(ctl)
        state["elapsed"] = time.monotonic() - state["sample_started"]
        loop.quit()
        return GLib.SOURCE_REMOVE

    def begin_sample():
        nonlocal gpu_process
        try:
            with open(gpu_path, "w", encoding="utf-8") as handle:
                gpu_process = subprocess.Popen(
                    GPU_COMMAND, stdout=handle, stderr=subprocess.DEVNULL)
        except OSError as exc:
            print(f"warning: GPU sampler unavailable: {exc}", file=sys.stderr)
        state["before"] = measure._sample_process_tree(ctl)
        state["sample_started"] = time.monotonic()
        GLib.timeout_add_seconds(duration, finish_sample)
        return GLib.SOURCE_REMOVE

    def on_load_changed(_view, event):
        if event == WebKit.LoadEvent.FINISHED and not state["loaded"]:
            state["loaded"] = True
            state["startup_ms"] = round((time.perf_counter() - started) * 1000, 2)
            GLib.timeout_add_seconds(warmup, begin_sample)

    for view in views:
        view.connect("load-changed", on_load_changed)

    def on_timeout():
        if state["after"] is None:
            state["timed_out"] = True
            loop.quit()
        return GLib.SOURCE_REMOVE

    timeout_id = GLib.timeout_add_seconds(max(30, warmup + duration + 20), on_timeout)
    try:
        loop.run()
    finally:
        if gpu_process is not None and gpu_process.poll() is None:
            gpu_process.terminate()
            gpu_process.wait(timeout=5)
        try:
            ctl.hide_viewer()
        except Exception:
            for window in windows:
                try:
                    window.close()
                    window.run_dispose()
                except Exception:
                    pass
        ctl._viewer_windows = []
        ctl._is_showing = False
        ctl._ephemeral_ctx = None
        gc.collect()

    if state["timed_out"] or state["after"] is None:
        raise RuntimeError(f"timed out measuring {scene_path.name} at {fps} FPS")
    metrics = measure._summarize_samples(
        state["before"], state["after"], state["elapsed"], os.sysconf("SC_CLK_TCK"))
    gpu_values = _gpu_busy_values(gpu_path.read_text(encoding="utf-8")) if gpu_path.is_file() else []
    return {
        "scene": scene_path.name,
        "fps_limit": fps,
        "fps_label": "native (uncapped)" if native else f"{fps} FPS",
        "startup_ms_to_load_finished": state["startup_ms"],
        "gpu_render_busy_percent_median": _median_or_none(gpu_values),
        "gpu_samples": len(gpu_values),
        **metrics,
    }


def _summarize(samples):
    groups = {}
    for sample in samples:
        groups.setdefault((sample["scene"], sample["fps_limit"]), []).append(sample)
    summary = []
    for (scene, fps), values in sorted(groups.items()):
        summary.append({
            "scene": scene,
            "fps_limit": fps,
            "fps_label": values[0]["fps_label"],
            "sample_count": len(values),
            "startup_ms_median": _median_or_none(
                [value["startup_ms_to_load_finished"] for value in values]),
            "cpu_percent_process_tree_median": _median_or_none(
                [value["cpu_percent_process_tree"] for value in values]),
            "rss_end_mib_sum_median": _median_or_none(
                [value["rss_end_mib_sum"] for value in values]),
            "gpu_render_busy_percent_median": _median_or_none(
                [value["gpu_render_busy_percent_median"] for value in values
                 if value["gpu_render_busy_percent_median"] is not None]),
        })
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fps", default="30,15", help="comma-separated FPS values (0 = native)")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--duration", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        fps_values = [int(value) for value in args.fps.split(",")]
    except ValueError:
        parser.error("--fps must be comma-separated integers")
    if not fps_values or any(value < 0 or value > 60 for value in fps_values):
        parser.error("FPS values must be between 0 and 60")
    if args.repeat < 1 or args.duration < 1 or args.warmup < 0:
        parser.error("invalid repeat/duration/warmup")

    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Gtk, GLib, WebKit  # noqa: F401
    except Exception as exc:
        print(f"error: GTK4/WebKitGTK 6.0 bindings required: {exc}", file=sys.stderr)
        return 2

    ctl = measure._load_ctl()
    Gtk.init()
    gpu_path = Path("/tmp/opencode/hardware-gpu.json")
    samples = []
    for scene_name in ("flow.html", "organic-harmonic-field.html"):
        scene_path = ROOT / "screensavers" / scene_name
        for fps in fps_values:
            for repeat in range(1, args.repeat + 1):
                print(f"Measuring {scene_name} at {fps} FPS (sample {repeat}/{args.repeat})...",
                      file=sys.stderr, flush=True)
                sample = _measure_one(ctl, Gtk, GLib, WebKit, scene_path, fps,
                                      args.warmup, args.duration, gpu_path)
                sample["repeat"] = repeat
                samples.append(sample)

    report = {
        "schema_version": 1,
        "environment": {
            "display": os.environ.get("XDG_SESSION_TYPE", "unknown"),
            "renderer": _renderer_string(),
            "gpu_tool": " ".join(GPU_COMMAND),
            "gpu_metric": "intel_gpu_top Render/3D busy %",
            "note": "Baselines from one desktop; repeat on additional target hardware before choosing budgets.",
        },
        "samples": samples,
        "summary_medians": _summarize(samples),
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
