"""Coverage for optional in-viewer scene rotation (#41)."""
import os
from pathlib import Path
import types
import unittest
from unittest import mock

import support
from material_screensaver_scene import next_scene_name, rotation_scene_names


class TestSharedSceneModule(unittest.TestCase):
    def test_pure_helpers_are_importable(self):
        available = {"a.html": "/x/a.html", "b.html": "/x/b.html"}
        self.assertEqual(rotation_scene_names({"favorites": ["b.html"]}, available), ["b.html"])
        self.assertEqual(
            next_scene_name({"active": "a.html"}, available),
            "b.html",
        )
        self.assertEqual(next_scene_name({}, available), "b.html")


class TestRotationConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_defaults_are_off_and_sane(self):
        cfg = self.ctl.config_store.normalize_config({})
        self.assertFalse(cfg["rotation_enabled"])
        self.assertEqual(cfg["rotation_interval_seconds"], 300)

    def test_normalization_rejects_invalid_values(self):
        normalize = self.ctl.config_store.normalize_config
        self.assertTrue(normalize({"rotation_enabled": True})["rotation_enabled"])
        self.assertFalse(normalize({"rotation_enabled": "true"})["rotation_enabled"])
        self.assertEqual(normalize({"rotation_interval_seconds": 30})["rotation_interval_seconds"], 30)
        self.assertEqual(normalize({"rotation_interval_seconds": 3600})["rotation_interval_seconds"], 3600)
        for bad in (0, 29, 3601, True, 60.5, None):
            with self.subTest(bad=bad):
                self.assertEqual(
                    normalize({"rotation_interval_seconds": bad})["rotation_interval_seconds"],
                    300,
                )


class TestRotationHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_uses_favorites_when_present_and_valid(self):
        available = {"a.html": "/x/a.html", "b.html": "/x/b.html", "c.html": "/x/c.html"}
        self.assertEqual(
            self.ctl._rotation_scene_names(
                {"favorites": ["c.html", "missing.html", "a.html"]}, available),
            ["c.html", "a.html"],
        )

    def test_falls_back_to_all_scenes_sorted(self):
        available = {"c.html": "/x/c.html", "a.html": "/x/a.html"}
        self.assertEqual(
            self.ctl._rotation_scene_names({"favorites": ["missing.html"]}, available),
            ["a.html", "c.html"],
        )

    def test_rotation_advances_each_webview_to_next_scene(self):
        ctl = support.load_ctl()
        loaded = []

        class FakeWeb:
            def load_uri(self, uri):
                loaded.append(uri)

        first = types.SimpleNamespace(_rotation_web=FakeWeb(), _rotation_scene="a.html")
        second = types.SimpleNamespace(_rotation_web=FakeWeb(), _rotation_scene="c.html")
        assigned = types.SimpleNamespace(
            _rotation_web=FakeWeb(), _rotation_scene="a.html", _rotation_locked=True)
        names = ("a.html", "b.html", "c.html")
        state = {
            "names": list(names),
            "available": {name: f"/x/{name}" for name in names},
            "windows": [first, second, assigned],
            "clock_format": "24h",
            "viewer_cfg": {},
        }
        with mock.patch.object(ctl, "_scene_uri",
                               side_effect=lambda path, fmt, cfg: f"file://{path}?{fmt}"):
            self.assertTrue(ctl._rotate_viewer_scenes(state))

        self.assertEqual(loaded, ["file:///x/b.html?24h", "file:///x/a.html?24h"])
        self.assertEqual(first._rotation_scene, "b.html")
        self.assertEqual(second._rotation_scene, "a.html")
        self.assertEqual(assigned._rotation_scene, "a.html")  # per-monitor assignment preserved

    def test_disabled_or_short_interval_does_not_arm(self):
        for cfg in (
            {"rotation_enabled": False},
            {"rotation_enabled": True, "rotation_interval_seconds": 10},
            {"rotation_enabled": True, "rotation_interval_seconds": True},
        ):
            with self.subTest(cfg=cfg):
                self.assertFalse(self.ctl._configure_viewer_rotation(cfg, [object()], "24h"))

    def test_single_scene_does_not_arm(self):
        original = self.ctl.list_screensavers
        self.ctl.list_screensavers = lambda: {"a.html": "/x/a.html"}
        try:
            cfg = {"rotation_enabled": True, "rotation_interval_seconds": 60}
            self.assertFalse(self.ctl._configure_viewer_rotation(cfg, [object()], "24h"))
        finally:
            self.ctl.list_screensavers = original


class TestRotationWiring(unittest.TestCase):
    def _read(self, relative):
        return (Path(support.REPO_ROOT) / relative).read_text(encoding="utf-8")

    def test_viewer_arms_rotation_and_reuses_webviews(self):
        source = self._read("bin/material-screensaver-ctl.py")
        self.assertIn("_configure_viewer_rotation(viewer_cfg, _viewer_windows, clock_format)", source)
        self.assertIn("win._rotation_web = web", source)
        self.assertIn("web.load_uri(_scene_uri(", source)
        # Scene switches must reuse the existing WebView, never spawn a viewer.
        self.assertNotIn("subprocess.Popen", source.split("def _rotate_viewer_scenes")[1].split("def ")[0])

    def test_gui_exposes_rotation_controls(self):
        source = self._read(os.path.join("bin", "material-screensaver-gui.py"))
        self.assertIn('title="Rotate scenes while active"', source)
        self.assertIn("self.rotation_switch.connect(\"notify::active\", self.on_rotation_toggled)", source)
        self.assertIn("self.rotation_interval_row.connect(\"notify::selected\", self.on_rotation_interval_changed)", source)
        self.assertIn("self.rotation_switch.set_active(cfg.get(\"rotation_enabled\", False))", source)
        self.assertIn("self._save_config(rotation_enabled=switch.get_active())", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
