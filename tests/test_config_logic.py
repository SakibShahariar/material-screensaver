"""Edge-case tests for config parsing and screensaver selection.

Loads bin/material-screensaver-ctl.py as a *logic-only* module: its GI imports
are all function-local, so these pure functions can be exercised with no GUI,
no WebKit, and no session bus. Great for CI.
"""
import json
import os
import tempfile
import unittest

import support


class CtlTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()
        cls.defaults = dict(cls.ctl.DEFAULT_CONFIG)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ms-savers-")
        self.savers_dir = os.path.join(self._tmp.name, "savers")
        os.makedirs(self.savers_dir)
        self.cfg_path = os.path.join(self._tmp.name, "config.json")
        self.ctl.SCREENSAVER_DIR = self.savers_dir
        self.ctl.CONFIG_PATH = self.cfg_path

    def tearDown(self):
        self._tmp.cleanup()
        self.ctl.SCREENSAVER_DIR = support.DEFAULT_SAVERS
        self.ctl.CONFIG_PATH = os.path.expanduser("~/.config/material-screensaver/config.json")

    def write_config(self, data):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def make_savers(self, *names):
        for n in names:
            with open(os.path.join(self.savers_dir, n), "w", encoding="utf-8") as f:
                f.write(f"<p>{n}</p>")


class TestValidIntEdgeCases(CtlTestCase):
    def test_bool_is_not_an_int(self):
        self.assertIsNone(self.ctl._valid_int(True, 1, 100))
        self.assertIsNone(self.ctl._valid_int(False, 1, 100))

    def test_bounds_inclusive(self):
        self.assertEqual(self.ctl._valid_int(1, 1, 100), 1)
        self.assertEqual(self.ctl._valid_int(100, 1, 100), 100)

    def test_out_of_range(self):
        self.assertIsNone(self.ctl._valid_int(0, 1, 100))
        self.assertIsNone(self.ctl._valid_int(101, 1, 100))
        self.assertIsNone(self.ctl._valid_int(-5, 1, 100))

    def test_non_int_types_rejected(self):
        for bad in ("abc", None, [5], {"v": 1}):
            self.assertIsNone(self.ctl._valid_int(bad, 1, 100), f"accepted {bad!r}")

    def test_fractional_float_rejected(self):
        # Lossy truncation (300.9 -> 300) silently corrupts user config.
        self.assertIsNone(self.ctl._valid_int(3.7, 1, 100))
        self.assertIsNone(self.ctl._valid_int(0.5, 1, 100))

    def test_integral_float_coerced(self):
        self.assertEqual(self.ctl._valid_int(3.0, 1, 100), 3)

    def test_numeric_string_coerced(self):
        self.assertEqual(self.ctl._valid_int("60", 1, 100), 60)


class TestNormalizeConfig(CtlTestCase):
    def test_none_gives_defaults(self):
        self.assertEqual(self.ctl.normalize_config(None), self.defaults)

    def test_non_dict_inputs_give_defaults(self):
        for bad in ("hello", [1, 2], 42, 3.14):
            self.assertEqual(self.ctl.normalize_config(bad), self.defaults, f"input {bad!r}")

    def test_empty_dict_gives_defaults(self):
        self.assertEqual(self.ctl.normalize_config({}), self.defaults)

    def test_valid_passthrough(self):
        cfg = {"active": "blob.html", "idle_seconds": 120, "lock_after_seconds": 60,
               "random": True, "close_on_mouse": False, "clock_format": "12h"}
        out = self.ctl.normalize_config(cfg)
        self.assertEqual(out["active"], "blob.html")
        self.assertEqual(out["idle_seconds"], 120)
        self.assertEqual(out["lock_after_seconds"], 60)
        self.assertIs(out["random"], True)
        self.assertNotIn("close_on_mouse", out)
        self.assertEqual(out["clock_format"], "12h")

    def test_active_must_be_str_or_none(self):
        out = self.ctl.normalize_config({"active": 42})
        self.assertIsNone(out["active"])

    def test_unknown_keys_dropped(self):
        out = self.ctl.normalize_config({"browser": "auto", "profile_root": "/tmp", "active": "flow.html"})
        self.assertNotIn("browser", out)
        self.assertNotIn("profile_root", out)

    def test_idle_seconds_range(self):
        self.assertEqual(self.ctl.normalize_config({"idle_seconds": 1})["idle_seconds"], 1)
        self.assertEqual(self.ctl.normalize_config({"idle_seconds": 86400})["idle_seconds"], 86400)
        # outside 1..86400 → revert to default 300
        for bad in (0, -1, 86401, 999999):
            self.assertEqual(self.ctl.normalize_config({"idle_seconds": bad})["idle_seconds"], 300,
                             f"idle_seconds={bad} not clamped to default")

    def test_idle_rejects_bool_and_junk(self):
        for bad in (True, False, "abc", None, "1h"):
            out = self.ctl.normalize_config({"idle_seconds": bad})
            self.assertEqual(out["idle_seconds"], 300, f"accepted idle_seconds={bad!r}")

    def test_lock_after_seconds_zero_ok(self):
        cfg = self.ctl.normalize_config({"lock_after_seconds": 0})
        self.assertEqual(cfg["lock_after_seconds"], 0)

    def test_lock_after_rejects_bool(self):
        cfg = self.ctl.normalize_config({"lock_after_seconds": True})
        self.assertEqual(cfg["lock_after_seconds"], 300)

    def test_clock_format_whitelist(self):
        for good in ("12h", "24h"):
            self.assertEqual(self.ctl.normalize_config({"clock_format": good})["clock_format"], good)
        for bad in ("12H", "24", "military", None, 12):
            self.assertEqual(self.ctl.normalize_config({"clock_format": bad})["clock_format"], "24h",
                             f"accepted clock_format={bad!r}")

    def test_boolean_flags_fall_back_to_default(self):
        # Invalid values for a bool flag must silently revert to the built-in
        # default FOR THAT KEY (random defaults False).
        for key in ("random",):
            default = self.defaults[key]
            for junkish in (1, 0, "true", "False", None, "yes", 3.14):
                out = self.ctl.normalize_config({key: junkish})
                self.assertIs(out[key], default,
                              f"{key}={junkish!r} should fall back to {default}")


class TestLoadConfig(CtlTestCase):
    def test_missing_file_gives_defaults(self):
        self.assertEqual(self.ctl.load_config(), self.defaults)

    def test_malformed_json_gives_defaults(self):
        with open(self.cfg_path, "w") as f:
            f.write("{not valid json!!")
        self.assertEqual(self.ctl.load_config(), self.defaults)

    def test_non_object_json_gives_defaults(self):
        self.write_config([1, 2, 3])
        self.assertEqual(self.ctl.load_config(), self.defaults)

    def test_valid_json_with_junk_normalized(self):
        self.write_config({"active": "koi.html", "idle_seconds": "abc", "browser": "chromium"})
        out = self.ctl.load_config()
        self.assertEqual(out["active"], "koi.html")
        self.assertEqual(out["idle_seconds"], 300)
        self.assertNotIn("browser", out)

    def test_reads_gui_config_from_nested_dir(self):
        # The GUI creates missing dirs then writes config.json there; the daemon
        # must pick it up from an arbitrary location.
        nested = os.path.join(self._tmp.name, "nope", "deep", "config.json")
        os.makedirs(os.path.dirname(nested), exist_ok=True)
        with open(nested, "w", encoding="utf-8") as f:
            json.dump({"active": "blob.html", "idle_seconds": 180}, f)
        self.ctl.CONFIG_PATH = nested
        out = self.ctl.load_config()
        self.assertEqual(out["active"], "blob.html")
        self.assertEqual(out["idle_seconds"], 180)


class TestListScreensavers(CtlTestCase):
    def test_only_html_files_matched(self):
        self.make_savers("blob.html", "flow.html", "notes.txt", ".hidden.html", "img.png")
        names = self.ctl.list_screensavers()
        self.assertEqual(list(names), ["blob.html", "flow.html"])

    def test_sorted_lexicographically(self):
        self.make_savers("b.html", "a.html", "c.html")
        self.assertEqual(list(self.ctl.list_screensavers()), ["a.html", "b.html", "c.html"])

    def test_unicode_and_special_chars_in_filenames(self):
        # User-added styles may have any filename; must survive URI usage later.
        self.make_savers("ko pond #1.html", "ザ・さくら.html", "naïve spaces.html", "plain.html")
        names = self.ctl.list_screensavers()
        self.assertIn("ko pond #1.html", names)
        self.assertIn("ザ・さくら.html", names)
        self.assertIn("naïve spaces.html", names)

    def test_empty_directory(self):
        self.assertEqual(self.ctl.list_screensavers(), {})


class TestGetActiveHTMLPath(CtlTestCase):
    def test_empty_dir_returns_none(self):
        self.assertIsNone(self.ctl.get_active_html_path(self.defaults))

    def test_active_picked(self):
        self.make_savers("a.html", "blob.html", "z.html")
        cfg = dict(self.defaults, active="blob.html")
        self.assertTrue(self.ctl.get_active_html_path(cfg).endswith("blob.html"))

    def test_unknown_active_falls_back_to_alphabetical_first(self):
        self.make_savers("b.html", "a.html", "c.html")
        cfg = dict(self.defaults, active="does-not-exist.html")
        self.assertEqual(os.path.basename(self.ctl.get_active_html_path(cfg)), "a.html")

    def test_none_active_falls_back_to_alphabetical_first(self):
        self.make_savers("zeta.html", "alpha.html")
        self.assertEqual(os.path.basename(self.ctl.get_active_html_path(self.defaults)), "alpha.html")

    def test_random_picks_some_valid_file(self):
        self.make_savers("one.html", "two.html", "three.html")
        cfg = dict(self.defaults, random=True, active=None)
        hits = {os.path.basename(self.ctl.get_active_html_path(cfg)) for _ in range(40)}
        self.assertTrue(hits <= {"one.html", "two.html", "three.html"}, f"unexpected picks: {hits}")
        self.assertEqual(len(hits), 3, "random mode should eventually pick every style")

    def test_unicode_active(self):
        self.make_savers("ザ・さくら.html", "plain.html")
        cfg = dict(self.defaults, active="ザ・さくら.html")
        self.assertEqual(os.path.basename(self.ctl.get_active_html_path(cfg)), "ザ・さくら.html")


class TestHasGraphicalSession(CtlTestCase):
    def test_empty_env(self):
        with tempfile.TemporaryDirectory() as d:
            self._unset("WAYLAND_DISPLAY", "DISPLAY")

    def _unset(self, *keys):
        import os as _os
        saved = {k: _os.environ.pop(k, None) for k in keys}
        try:
            self.assertFalse(self.ctl.has_graphical_session())
        finally:
            for k, v in saved.items():
                if v is not None:
                    _os.environ[k] = v


if __name__ == "__main__":
    unittest.main(verbosity=2)