"""Budget derivation and comparison for scene performance measurements."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


derive = _load("derive_budgets", "derive-performance-budgets.py")
check = _load("check_budgets", "check-performance-budgets.py")


class TestPerformanceBudgets(unittest.TestCase):
    def test_derives_budgets_with_margin_from_worst_sample(self):
        report = {"samples": [
            {"scene": "a.html", "fps_limit": 30, "startup_ms_to_load_finished": 100,
             "cpu_percent_process_tree": 40, "rss_end_mib_sum": 300,
             "gpu_render_busy_percent_median": 60},
            {"scene": "a.html", "fps_limit": 30, "startup_ms_to_load_finished": 120,
             "cpu_percent_process_tree": 50, "rss_end_mib_sum": 320,
             "gpu_render_busy_percent_median": 70},
        ]}
        budgets = derive.derive(report)["a.html"]["30"]
        self.assertEqual(budgets["startup_ms"], 200)
        self.assertEqual(budgets["cpu_percent"], 75)
        self.assertEqual(budgets["rss_mib"], 420)
        self.assertEqual(budgets["gpu_busy_percent"], 100)  # capped

    def test_flags_only_values_over_budget(self):
        report = {"summary_medians": [
            {"scene": "a.html", "fps_limit": 30, "fps_label": "30 FPS",
             "startup_ms_median": 100, "cpu_percent_process_tree_median": 80,
             "rss_end_mib_sum_median": 300, "gpu_render_busy_percent_median": 40},
        ]}
        budgets = {"budgets": {"a.html": {"30": {
            "startup_ms": 200, "cpu_percent": 75, "rss_mib": 400,
            "gpu_busy_percent": 100,
        }}}}
        violations = check.find_violations(report, budgets)
        self.assertEqual(len(violations), 1)
        self.assertIn("process-tree CPU % 80 exceeds budget 75", violations[0])

    def test_committed_profiles_are_consistent(self):
        for name in ("ci-budgets.json", "hardware-budgets.json"):
            data = json.loads((ROOT / "docs" / "performance" / name).read_text(
                encoding="utf-8"))
            self.assertIn("budgets", data)
            self.assertIn("flow.html", data["budgets"])
            self.assertIn("organic-harmonic-field.html", data["budgets"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
