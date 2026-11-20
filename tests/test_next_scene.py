"""Coverage for the NextScene control used by the status menu (#52)."""
import json
import os
import tempfile
import unittest
from unittest import mock

import support


class TestNextScene(unittest.TestCase):
    def setUp(self):
        self.ctl = support.load_ctl()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = os.path.join(self.temp.name, "config.json")
        self.available = {"a.html": "/x/a.html", "b.html": "/x/b.html", "c.html": "/x/c.html"}

    def _run(self, active):
        with mock.patch.object(self.ctl, "CONFIG_PATH", self.config_path), \
             mock.patch.object(self.ctl, "list_screensavers", lambda: self.available), \
             mock.patch.object(self.ctl, "load_config",
                               lambda: {"active": active, "favorites": []}), \
             mock.patch.object(self.ctl, "is_viewer_active", lambda: False):
            self.assertTrue(self.ctl.next_scene())
        with open(self.config_path, encoding="utf-8") as handle:
            return json.load(handle)["active"]

    def test_advances_to_next_scene(self):
        self.assertEqual(self._run("a.html"), "b.html")

    def test_wraps_around(self):
        self.assertEqual(self._run("c.html"), "a.html")

    def test_unknown_active_starts_from_first(self):
        self.assertEqual(self._run("missing.html"), "b.html")

    def test_dbus_interface_exposes_next_scene(self):
        import pathlib
        source = (pathlib.Path(support.REPO_ROOT) / "bin" / "material-screensaver-ctl.py").read_text(
            encoding="utf-8")
        self.assertIn('<method name="NextScene"/>', source)
        self.assertIn('elif method == "NextScene":', source)
        self.assertIn('elif action == "next":', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
