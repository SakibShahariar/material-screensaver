"""Coverage for the optional top-bar status menu (#52)."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

import support

EXT = "material-screensaver-gestures@io.github.sakib"


class TestStatusMenuConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_disabled_by_default_and_validated(self):
        normalize = self.ctl.config_store.normalize_config
        self.assertFalse(normalize({})["status_menu_enabled"])
        self.assertTrue(normalize({"status_menu_enabled": True})["status_menu_enabled"])
        self.assertFalse(normalize({"status_menu_enabled": "true"})["status_menu_enabled"])

    def test_gui_exposes_toggle(self):
        source = (Path(support.REPO_ROOT) / "bin" / "material-screensaver-gui.py").read_text(
            encoding="utf-8")
        self.assertIn('title="Status menu"', source)
        self.assertIn("self.status_menu_switch.connect(\"notify::active\", self.on_status_menu_toggled)", source)
        self.assertIn("self._save_config(status_menu_enabled=switch.get_active())", source)


class TestShellExtension(unittest.TestCase):
    def _ext_path(self, name):
        return Path(support.REPO_ROOT) / "extensions" / EXT / name

    def test_js_syntax(self):
        source = self._ext_path("extension.js").read_text(encoding="utf-8")
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as handle:
            handle.write(source)
            tmp = handle.name
        try:
            result = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        finally:
            os.remove(tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_status_menu_is_gated_and_uses_daemon_dbus(self):
        source = self._ext_path("extension.js").read_text(encoding="utf-8")
        self.assertIn("status_menu_enabled", source)
        self.assertIn("Main.panel.addToStatusArea", source)
        self.assertIn("Gio.bus_watch_name", source)
        self.assertIn("Gio.bus_unwatch_name", source)
        for method in ("Show", "Hide", "Toggle", "NextScene", "IsActive"):
            self.assertIn(method, source)
        self.assertIn('new PopupMenu.PopupMenuItem("Next Scene")', source)
        self.assertIn("material-screensaver-settings.desktop", source)
        self.assertNotIn("Shell.Eval", source)
        # Gesture guard must remain intact.
        self.assertIn("if (fingers < 3)", source)
        # GJS requires the priority argument; a 2-arg call throws in GNOME 51
        # and leaves the status indicator without its state-sync poll.
        self.assertIn("GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2,", source)
        self.assertNotIn("GLib.timeout_add_seconds(2,", source)
        self.assertIn('icon_name: "preferences-desktop-screensaver-symbolic"', source)

    def test_metadata_version_bumped(self):
        metadata = json.loads(self._ext_path("metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["version"], 5)
        self.assertIn("status menu", metadata["description"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
