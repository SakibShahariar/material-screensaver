"""Logic-only tests for the settings GUI (bin/material-screensaver-gui.py).

The GUI module imports GI at import time; these run when GI + Gtk + Adw are
available (CI installs them). Skipped silently otherwise.
"""
import json
import os
import tempfile
import unittest

import support


def _gi_ok():
    try:
        import gi  # noqa: F401
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        return True
    except Exception:
        return False


@unittest.skipUnless(_gi_ok(), "GI/GTK unavailable; GUI logic tests skipped")
class TestGuiLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.gui = support.load_gui()
        except Exception as e:
            raise unittest.SkipTest(f"cannot load GUI module: {e}")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ms-gui-")
        self.gui.CONFIG_PATH = os.path.join(self._tmp.name, "config.json")
        self.gui.SCREENSAVER_DIR = os.path.join(self._tmp.name, "savers")
        os.makedirs(self.gui.SCREENSAVER_DIR, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()
        self.gui.CONFIG_PATH = os.path.expanduser("~/.config/material-screensaver/config.json")
        self.gui.SCREENSAVER_DIR = os.path.expanduser("~/.local/share/material-screensaver/screensavers")

    def _write(self, data):
        with open(self.gui.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_display_name(self):
        cases = {
            "blob.html": "Blob",
            "wave-function-collapse.html": "Wave Function Collapse",
            "n_body_galaxies.html": "N Body Galaxies",
            "solar-system.html": "Solar System",
            "koi.html": "Koi",
        }
        for fname, want in cases.items():
            self.assertEqual(self.gui.display_name(fname), want, fname)

    def test_keybinding_read_does_not_register_but_create_does(self):
        class FakeParent:
            def __init__(self):
                self.paths = []
            def get_strv(self, _key):
                return list(self.paths)
            def set_strv(self, _key, value):
                self.paths = list(value)

        class FakeChild:
            def __init__(self):
                self.values = {"command": "", "name": "", "binding": ""}
            def get_string(self, key):
                return self.values.get(key, "")
            def set_string(self, key, value):
                self.values[key] = value

        parent, child = FakeParent(), FakeChild()
        class FakeSettings:
            @staticmethod
            def new(_schema):
                return parent
            @staticmethod
            def new_with_path(_schema, _path):
                return child

        original = self.gui.Gio.Settings
        self.gui.Gio.Settings = FakeSettings
        try:
            self.assertIsNone(self.gui.get_keybinding_settings())
            self.assertEqual(parent.paths, [])
            settings = self.gui.get_keybinding_settings(create=True)
            self.assertIs(settings, child)
            self.assertEqual(parent.paths, [self.gui.KEYBINDING_PATH])
            self.assertEqual(child.values["name"], "Material Screensaver")
            self.assertEqual(child.values["command"], f"{self.gui.CTL_SCRIPT} toggle")
        finally:
            self.gui.Gio.Settings = original

    def test_display_name_reads_scene_title(self):
        path = os.path.join(self.gui.SCREENSAVER_DIR, "gameoflife.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write("<html><head><title>Material Screensaver — Game of Life</title></head></html>")
        self.assertEqual(self.gui.display_name("gameoflife.html"), "Game of Life")

    def test_display_name_multidot(self):
        # glob never emits dotfiles, but multi-dot stems are real (e.g. "koi.pond")
        self.assertEqual(self.gui.display_name("foo.bar.html"), "Foo.Bar")

    def test_normalize_config_parity_with_ctl(self):
        # GUI and daemon each have a copy; they must agree on edge cases.
        ctl = support.load_ctl()
        cases = [
            None, {}, [], "x",
            {"idle_seconds": 0},
            {"idle_seconds": 3.7},
            {"idle_seconds": True},
            {"random": 1},
            {"clock_format": "12H"},
            {"lock_after_seconds": -2},
            {"matugen_colors_path": "/tmp/custom-colors.css"},
            {"matugen_colors_path": "relative.css"},
            {"active": 42},
        ]
        for case in cases:
            self.assertEqual(self.gui.normalize_config(case),
                             ctl.normalize_config(case),
                             f"gui/ctl disagree on {case!r}")

    def test_save_config_atomic_and_roundtrip(self):
        self.gui.save_config(active="blob.html", idle_seconds=123)
        self.assertTrue(os.path.isfile(self.gui.CONFIG_PATH))
        # The unique temporary file is removed after an atomic replacement.
        leftovers = [name for name in os.listdir(self._tmp.name) if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        cfg = self.gui.load_config()
        self.assertEqual(cfg["active"], "blob.html")
        self.assertEqual(cfg["idle_seconds"], 123)

    def test_save_config_propagates_atomic_write_failure(self):
        original = self.gui.os.replace
        self.gui.os.replace = lambda *_args: (_ for _ in ()).throw(OSError("read-only filesystem"))
        try:
            with self.assertRaisesRegex(OSError, "read-only filesystem"):
                self.gui.save_config(active="blob.html")
        finally:
            self.gui.os.replace = original
        leftovers = [name for name in os.listdir(self._tmp.name) if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_save_preserves_other_keys(self):
        self._write({"active": "a.html", "clock_format": "12h", "random": True})
        self.gui.save_config(idle_seconds=600)
        cfg = self.gui.load_config()
        self.assertEqual(cfg["active"], "a.html")
        self.assertEqual(cfg["clock_format"], "12h")
        self.assertIs(cfg["random"], True)
        self.assertEqual(cfg["idle_seconds"], 600)

    def test_gui_picker_uses_only_html(self):
        for n in ("a.html", "b.html", "readme.txt"):
            with open(os.path.join(self.gui.SCREENSAVER_DIR, n), "w") as f:
                f.write("<p>x</p>")
        self.assertEqual(self.gui.list_screensavers(), ["a.html", "b.html"])

    def test_preview_no_longer_blanked_by_random(self):
        # Regression guard: the preview must never blank; in random mode it must
        # pick a random style instead of the combo selection.
        with open(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-gui.py"),
                  encoding="utf-8") as f:
            src = f.read()
        start = src.index("    def _update_preview(self):")
        end = src.index("    def refresh_shortcut_label(self):")
        fn = src[start:end]
        self.assertNotIn("about:blank", fn)
        self.assertIn('if cfg.get("random", False):', fn)
        self.assertIn("random.randrange", fn)
        self.assertIn('self.preview_web.load_uri(uri)', fn)

    def test_preview_clickable(self):
        # Clicking the live preview must load the next style (a random one in
        # random mode) by re-running _update_preview.
        with open(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-gui.py"),
                  encoding="utf-8") as f:
            src = f.read()
        self.assertIn("Gtk.GestureClick()", src)
        self.assertIn('self.preview_web.add_controller(click)', src)
        self.assertIn('click.connect("pressed", lambda *_', src)

    def test_matugen_link_tracks_configured_target(self):
        first = os.path.join(self._tmp.name, "first.css")
        second = os.path.join(self._tmp.name, "second.css")
        cfg = dict(self.gui.DEFAULT_CONFIG, matugen_colors_path=first)
        self.assertTrue(self.gui.sync_matugen_colors_link(cfg))
        link = os.path.join(self.gui.SCREENSAVER_DIR, "matugen-colors.css")
        self.assertEqual(os.readlink(link), first)
        self.assertTrue(self.gui.sync_matugen_colors_link(
            dict(cfg, matugen_colors_path=second)
        ))
        self.assertEqual(os.readlink(link), second)

    def test_cli_lists_scenes_without_opening_gui(self):
        import contextlib
        import io

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.gui.main(["--list-screensavers"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().splitlines(), [])

    def test_cli_rejects_unknown_or_traversal_preview(self):
        import contextlib
        import io

        for scene in ("missing.html", "../blob.html", "/tmp/blob.html"):
            with self.subTest(scene=scene):
                error = io.StringIO()
                with contextlib.redirect_stderr(error):
                    result = self.gui.main(["--preview", scene])
                self.assertEqual(result, 2)
                self.assertIn("Unknown screensaver scene", error.getvalue())

    def test_matugen_path_setting_is_present_and_applied(self):
        with open(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-gui.py"),
                  encoding="utf-8") as f:
            src = f.read()
        self.assertIn('title="Colors stylesheet"', src)
        self.assertIn('self.matugen_path_apply.connect("clicked", self.on_matugen_path_apply)', src)
        self.assertIn('self._save_config(matugen_colors_path=path)', src)
        self.assertIn("sync_matugen_colors_link(cfg)", src)
        self.assertIn("self.matugen_path_entry.set_text(cfg.get(\"matugen_colors_path\", DEFAULT_MATUGEN_COLORS_PATH))", src)

    def test_gui_random_import_present(self):
        with open(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-gui.py"),
                  encoding="utf-8") as f:
            src = f.read()
        self.assertIn("\nimport random\n", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)