"""Packaging / install-path sanity: install.sh, desktop file, systemd unit, shell extension."""
import json
import os
import re
import subprocess
import unittest

import support

EXT_UUID = "material-screensaver-gestures@io.github.sakib"


class TestScriptsAndUnits(unittest.TestCase):
    def _read(self, rel):
        with open(os.path.join(support.REPO_ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_install_sh_bash_syntax(self):
        r = subprocess.run(["bash", "-n", os.path.join(support.REPO_ROOT, "install.sh")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_desktop_exec_uses_resolvable_path(self):
        text = self._read("applications/material-screensaver-settings.desktop")
        m = re.search(r"^Exec=(.+)$", text, re.M)
        self.assertIsNotNone(m, "no Exec= line")
        self.assertTrue(m.group(1).startswith("%h/.local/bin/material-screensaver-gui.py"),
                        f"Exec should use %h/.local/bin, got: {m.group(1)}")

    def test_desktop_icon_matches_install_target(self):
        text = self._read("applications/material-screensaver-settings.desktop")
        m = re.search(r"^Icon=(.+)$", text, re.M)
        self.assertEqual(m.group(1).strip() if m else "", "material-screensaver",
                         "desktop Icon= must match installer's icon target basename")

    def test_systemd_unit_launches_daemon(self):
        text = self._read("systemd/material-screensaver.service")
        self.assertIn("ExecStart=%h/.local/bin/material-screensaver-ctl.py daemon", text)
        self.assertIn("WantedBy=graphical-session.target", text)

    def test_gui_and_ctl_exist_and_are_python(self):
        for f in ("material-screensaver-gui.py", "material-screensaver-ctl.py"):
            p = os.path.join(support.REPO_ROOT, "bin", f)
            self.assertTrue(os.path.isfile(p), f"missing {f}")
            with open(p) as fh:
                self.assertTrue(fh.read(2) == "#!",
                                f"{f} missing shebang")


class TestShellExtension(unittest.TestCase):
    """The 3-finger-swipe guard shell extension ships intact and install.sh wires it."""

    def _ext_dir(self, *parts):
        return os.path.join(support.REPO_ROOT, "extensions", EXT_UUID, *parts)

    def test_files_present(self):
        self.assertTrue(os.path.isfile(self._ext_dir("extension.js")))
        self.assertTrue(os.path.isfile(self._ext_dir("metadata.json")))

    def test_metadata_valid_and_scoped(self):
        with open(self._ext_dir("metadata.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["uuid"], EXT_UUID)
        self.assertIsInstance(meta["shell-version"], list)
        self.assertGreaterEqual(meta["shell-version"][0], "45",
                                "Eval is disabled on GNOME 45+, guard must use extension API")

    def test_extension_js_syntax(self):
        # ESM parse check (cannot import under real GJS outside the shell).
        import tempfile
        with open(self._ext_dir("extension.js"), encoding="utf-8") as g:
            js = g.read()
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as f:
            f.write(js)
            tmp = f.name
        try:
            r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        finally:
            os.remove(tmp)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_extension_js_blocks_swipes(self):
        with open(self._ext_dir("extension.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("Clutter.EventType.TOUCHPAD_SWIPE", js)
        self.assertIn("get_touchpad_gesture_finger_count", js)
        self.assertIn('const VIEWER_TITLE = "Material Screensaver"', js)
        self.assertIn("win.get_title() === VIEWER_TITLE", js)
        self.assertIn("win.is_fullscreen()", js)

    def test_install_sh_copies_and_enables_extension(self):
        text = subprocess.run(["bash", "-n", os.path.join(support.REPO_ROOT, "install.sh")],
                              capture_output=True, text=True)
        self.assertEqual(text.returncode, 0)
        sh = self._read_sh()
        self.assertIn(f'"$EXT_BASE/$EXT_UUID"', sh)
        self.assertIn("enabled-extensions", sh)

    def _read_sh(self):
        with open(os.path.join(support.REPO_ROOT, "install.sh"), encoding="utf-8") as f:
            return f.read()


if __name__ == "__main__":
    unittest.main(verbosity=2)