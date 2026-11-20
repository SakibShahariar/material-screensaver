"""Coverage for the optional viewer fade transitions (#49)."""
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import support


class TestTransitionConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_disabled_by_default_and_validated(self):
        normalize = self.ctl.config_store.normalize_config
        self.assertFalse(normalize({})["transitions_enabled"])
        self.assertTrue(normalize({"transitions_enabled": True})["transitions_enabled"])
        self.assertFalse(normalize({"transitions_enabled": "true"})["transitions_enabled"])

    def test_opacity_interpolation(self):
        at = self.ctl._opacity_at
        self.assertAlmostEqual(at(0.0, 1.0, 0, 200), 0.0)
        self.assertAlmostEqual(at(0.0, 1.0, 100, 200), 0.5)
        self.assertAlmostEqual(at(0.0, 1.0, 500, 200), 1.0)
        self.assertAlmostEqual(at(1.0, 0.0, 100, 200), 0.5)
        self.assertAlmostEqual(at(0.2, 0.9, 10, 0), 0.9)


class TestFadeAnimation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_fade_steps_call_set_opacity_and_completion(self):
        callbacks = []

        class FakeGLib:
            @staticmethod
            def timeout_add(interval, callback, *args):
                callbacks.append((interval, callback))
                return 1

        fake_gi = types.ModuleType("gi")
        fake_repo = types.ModuleType("gi.repository")
        fake_repo.GLib = FakeGLib
        with mock.patch.dict(sys.modules, {"gi": fake_gi, "gi.repository": fake_repo}):
            done = []
            widget = types.SimpleNamespace(opacity=0.0)
            widget.get_opacity = lambda: widget.opacity
            widget.set_opacity = lambda value: setattr(widget, "opacity", value)
            self.ctl._fade_opacity(widget, 1.0, 32, lambda: done.append(True))

        self.assertEqual(len(callbacks), 1)
        interval, tick = callbacks[0]
        self.assertGreaterEqual(interval, 16)
        while tick():  # run the animation to completion
            pass
        self.assertEqual(widget.opacity, 1.0)
        self.assertEqual(done, [True])


class TestTransitionWiring(unittest.TestCase):
    def _read(self, relative):
        return (Path(support.REPO_ROOT) / relative).read_text(encoding="utf-8")

    def test_viewer_uses_opt_in_fades(self):
        source = self._read("bin/material-screensaver-ctl.py")
        self.assertGreaterEqual(source.count('viewer_cfg.get("transitions_enabled", False)'), 2)
        self.assertIn("_fade_opacity(w, 1.0, 180)", source)
        self.assertIn("_fade_opacity(_viewer_windows[0], 0.0, 150, finish)", source)

    def test_gui_exposes_transition_toggle(self):
        source = self._read("bin/material-screensaver-gui.py")
        self.assertIn('title="Fade transitions"', source)
        self.assertIn("self.transitions_switch.connect(\"notify::active\", self.on_transitions_toggled)", source)
        self.assertIn("self._save_config(transitions_enabled=switch.get_active())", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
