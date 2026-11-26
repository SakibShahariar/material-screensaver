"""Monitor enumeration and per-window coverage logging (#6)."""
from pathlib import Path
import unittest

import support


class FakeModel:
    def __init__(self, items):
        self.items = items

    def get_n_items(self):
        return len(self.items)

    def get_item(self, index):
        return self.items[index]


class FakeDisplay:
    def __init__(self, model=None, error=None):
        self.model = model
        self.error = error

    def get_monitors(self):
        if self.error is not None:
            raise self.error
        return self.model


class TestMonitorCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_returns_one_entry_per_connected_monitor(self):
        monitors = [object(), object(), object()]
        self.assertEqual(
            self.ctl._monitors_for_display(FakeDisplay(FakeModel(monitors))), monitors)

    def test_falls_back_to_single_screen_when_no_monitors(self):
        self.assertEqual(self.ctl._monitors_for_display(FakeDisplay(FakeModel([]))), [None])
        self.assertEqual(self.ctl._monitors_for_display(None), [None])

    def test_enumeration_error_falls_back(self):
        display = FakeDisplay(error=RuntimeError("display gone"))
        self.assertEqual(self.ctl._monitors_for_display(display), [None])

    def test_viewer_logs_one_event_per_monitor(self):
        source = (Path(support.REPO_ROOT) / "bin" / "material-screensaver-ctl.py").read_text(
            encoding="utf-8")
        self.assertIn("for monitor_index, mon in enumerate(monitors):", source)
        self.assertIn('monitors = _monitors_for_display(display)', source)
        block = source[source.index("for monitor_index, mon in enumerate(monitors):"):
                       source.index("win.add_css_class(\"screensaver-window\")")]
        event = block[block.index('_log_event('):block.index('_log_event(') + 260]
        self.assertIn('"viewer_window_created"', event)
        self.assertIn("monitor_index=monitor_index", event)
        self.assertIn("width=win.get_default_size()[0]", event)


if __name__ == "__main__":
    unittest.main(verbosity=2)
