#!/usr/bin/env python3
"""Collect headless startup, CPU, and memory samples for representative scenes.

This produces measurements, not pass/fail budgets. Xvfb uses software rendering,
so GPU utilization is deliberately reported as unavailable.
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))


def _read_process_metrics(proc_root: str, pid: int):
    """Return (starttime, CPU ticks, resident KiB) for one process."""
    try:
        with open(os.path.join(proc_root, str(pid), "stat"), encoding="utf-8") as stream:
            stat = stream.read()
        tail = stat[stat.rfind(")") + 2:].split()
        if len(tail) < 20:
            return None
        start_time = tail[19]
        cpu_ticks = int(tail[11]) + int(tail[12])
        resident_kib = 0
        with open(os.path.join(proc_root, str(pid), "status"), encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    resident_kib = int(line.split()[1])
                    break
        return start_time, cpu_ticks, resident_kib
    except (OSError, ValueError, IndexError):
        return None


def _sample_process_tree(ctl, root_pid: int | None = None, proc_root: str = "/proc"):
    if root_pid is None:
        root_pid = os.getpid()
    pids = {root_pid}
    pids.update(row[0] for row in ctl._discover_proc_descendants(proc_root, root_pid))
    return {
        pid: metrics
        for pid in pids
        if (metrics := _read_process_metrics(proc_root, pid)) is not None
    }


def _summarize_samples(before, after, elapsed_seconds: float, ticks_per_second: int):
    shared = [
        (pid, start[0], start[1], after[pid][1])
        for pid, start in before.items()
        if pid in after and after[pid][0] == start[0]
    ]
    cpu_ticks = sum(max(0, end_ticks - start_ticks)
                    for _pid, _identity, start_ticks, end_ticks in shared)
    cpu_percent = (
        (cpu_ticks / ticks_per_second) / elapsed_seconds * 100
        if elapsed_seconds > 0 and ticks_per_second > 0 else None
    )
    rss_start = sum(value[2] for value in before.values())
    rss_end = sum(value[2] for value in after.values())
    return {
        "cpu_percent_process_tree": round(cpu_percent, 2) if cpu_percent is not None else None,
        "rss_start_mib_sum": round(rss_start / 1024, 2),
        "rss_end_mib_sum": round(rss_end / 1024, 2),
        "process_count_start": len(before),
        "process_count_end": len(after),
        "cpu_processes_compared": len(shared),
    }


def _load_ctl():
    spec = importlib.util.spec_from_file_location(
        "material_screensaver_ctl_benchmark", BIN / "material-screensaver-ctl.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load viewer control module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _webviews_from_windows(windows):
    views = []
    for window in windows:
        overlay = window.get_child()
        view = overlay.get_child() if overlay is not None else None
        if view is None:
            raise RuntimeError("viewer window did not contain a WebView")
        views.append(view)
    if not views:
        raise RuntimeError("viewer created no windows")
    return views


def _measure_one(ctl, Gtk, GLib, WebKit, scene_path: Path, fps: int, warmup: int, duration: int):
    config = dict(ctl.DEFAULT_CONFIG)
    config.update({
        "fps_limit": fps,
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
    views = _webviews_from_windows(windows)
    loop = GLib.MainLoop()
    state = {"loaded": False, "startup_ms": None, "before": None, "after": None,
             "elapsed": None, "timed_out": False}

    timeout_id = None

    def finish_sample():
        if timeout_id is not None:
            try:
                GLib.source_remove(timeout_id)
            except Exception:
                pass
        state["after"] = _sample_process_tree(ctl)
        state["elapsed"] = time.monotonic() - state["sample_started"]
        loop.quit()
        return GLib.SOURCE_REMOVE

    def begin_sample():
        state["before"] = _sample_process_tree(ctl)
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
        try:
            # Use the application's own teardown path so fullscreen retries,
            # WebKit helpers, and pending GLib sources are cleaned consistently.
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
        raise RuntimeError(f"timed out loading or measuring {scene_path.name} at {fps} FPS")
    metrics = _summarize_samples(
        state["before"], state["after"], state["elapsed"], os.sysconf("SC_CLK_TCK")
    )
    return {
        "scene": scene_path.name,
        "scene_type": (
            "WebGL2" if scene_path.name == "quantum-interference.html"
            else "WebGL" if scene_path.name == "organic-harmonic-field.html"
            else "Canvas 2D"
        ),
        "fps_limit": fps,
        "startup_ms_to_load_finished": state["startup_ms"],
        "measurement_seconds": round(state["elapsed"], 2),
        **metrics,
        "gpu_utilization_percent": None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fps", default="30,15", help="comma-separated FPS caps to sample")
    parser.add_argument("--duration", type=int, default=4, help="steady-state sample duration")
    parser.add_argument("--warmup", type=int, default=1, help="seconds to warm up after page load")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args(argv)
    try:
        fps_values = [int(value) for value in args.fps.split(",")]
    except ValueError:
        parser.error("--fps must be a comma-separated list of integers")
    if not fps_values or any(value < 10 or value > 60 for value in fps_values):
        parser.error("FPS values must be between 10 and 60")
    if args.duration < 1 or args.warmup < 0:
        parser.error("--duration must be positive and --warmup cannot be negative")

    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Gtk, GLib, WebKit  # noqa: F401
    except Exception as exc:
        print(f"error: GTK4/WebKitGTK 6.0 GI bindings are required: {exc}", file=sys.stderr)
        return 2

    ctl = _load_ctl()
    Gtk.init()
    samples = []
    for scene_name in ("solar-system.html", "organic-harmonic-field.html"):
        scene_path = ROOT / "screensavers" / scene_name
        if not scene_path.is_file():
            print(f"error: required benchmark scene missing: {scene_path}", file=sys.stderr)
            return 2
        for fps in fps_values:
            print(f"Measuring {scene_name} at {fps} FPS...", file=sys.stderr, flush=True)
            samples.append(_measure_one(ctl, Gtk, GLib, WebKit, scene_path, fps, args.warmup, args.duration))

    report = {
        "schema_version": 1,
        "environment": {
            "display": "Xvfb",
            "renderer": "software (LIBGL_ALWAYS_SOFTWARE=1)",
            "gpu_utilization": "unavailable in this headless CI environment",
            "memory_note": "RSS is summed across the process tree; shared pages may be counted more than once.",
            "budget_enforcement": "not enabled; collect repeatable baselines before choosing thresholds",
        },
        "samples": samples,
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
