"""Unit tests for the headless scene performance sampler."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "measure-scene-performance.py"
spec = importlib.util.spec_from_file_location("scene_performance", SCRIPT)
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


class TestScenePerformanceMetrics(unittest.TestCase):
    def _write_proc(self, root, pid, start, user_ticks, system_ticks, rss_kib):
        process_dir = Path(root) / str(pid)
        process_dir.mkdir(parents=True)
        tail = ["S", "1"] + ["0"] * 9 + [
            str(user_ticks), str(system_ticks)
        ] + ["0"] * 6 + [str(start)]
        (process_dir / "stat").write_text(
            f"{pid} (benchmark test) {' '.join(tail)}", encoding="utf-8"
        )
        (process_dir / "status").write_text(
            f"Name:\ttest\nVmRSS:\t{rss_kib} kB\n", encoding="utf-8"
        )

    def test_reads_start_time_cpu_ticks_and_rss(self):
        with tempfile.TemporaryDirectory() as temp:
            self._write_proc(temp, 123, 456, 12, 8, 4096)
            self.assertEqual(measure._read_process_metrics(temp, 123), ("456", 20, 4096))

    def test_cpu_delta_ignores_reused_pid(self):
        before = {123: ("old-start", 100, 2048), 124: ("same-start", 200, 1024)}
        after = {123: ("new-start", 1000, 4096), 124: ("same-start", 300, 2048)}
        metrics = measure._summarize_samples(before, after, 2.0, 100)
        self.assertEqual(metrics["cpu_percent_process_tree"], 50.0)
        self.assertEqual(metrics["cpu_processes_compared"], 1)
        self.assertEqual(metrics["rss_end_mib_sum"], 6.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
