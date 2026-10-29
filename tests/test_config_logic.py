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


class TestBatteryPolicyLabel(CtlTestCase):
    def test_label_only_appears_when_battery_saving_is_active(self):
        self.assertIsNone(self.ctl._battery_policy_label({"fps_limit": 30}, False))
        self.assertEqual(
            self.ctl._battery_policy_label({"fps_limit": 30}, True),
            "Battery saver active · FPS cap 15",
        )
        self.assertEqual(
            self.ctl._battery_policy_label({"fps_limit": 10}, True),
            "Battery saver active · FPS cap 10",
        )
        self.assertEqual(
            self.ctl._battery_policy_label({"fps_limit": True}, True),
            "Battery saver active · FPS cap 15",
        )


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

    def test_onboarding_dismissal_state_is_persisted_and_validated(self):
        self.assertFalse(self.ctl.normalize_config({})["onboarding_dismissed"])
        self.assertTrue(self.ctl.normalize_config({"onboarding_dismissed": True})["onboarding_dismissed"])
        self.assertFalse(self.ctl.normalize_config({"onboarding_dismissed": "true"})["onboarding_dismissed"])
        self.ctl.config_store.save_config(self.cfg_path, onboarding_dismissed=True)
        self.assertTrue(self.ctl.load_config()["onboarding_dismissed"])

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

    def test_battery_fps_saving_defaults_to_enabled_and_validates(self):
        self.assertTrue(self.ctl.normalize_config({})["reduce_fps_on_battery"])
        self.assertFalse(self.ctl.normalize_config({"reduce_fps_on_battery": False})["reduce_fps_on_battery"])
        self.assertTrue(self.ctl.normalize_config({"reduce_fps_on_battery": "false"})["reduce_fps_on_battery"])

    def test_blank_display_timeout_defaults_and_validates(self):
        self.assertEqual(self.ctl.normalize_config({})["blank_display_after_minutes"], 0)
        for good in (0, 1, 30, 1440):
            self.assertEqual(
                self.ctl.normalize_config({"blank_display_after_minutes": good})["blank_display_after_minutes"],
                good,
            )
        for bad in (-1, 1441, True, 1.5, "30", None):
            self.assertEqual(
                self.ctl.normalize_config({"blank_display_after_minutes": bad})["blank_display_after_minutes"],
                0,
                f"accepted blank_display_after_minutes={bad!r}",
            )
        self.ctl.config_store.save_config(self.cfg_path, blank_display_after_minutes=15)
        self.assertEqual(self.ctl.load_config()["blank_display_after_minutes"], 15)

    def test_fps_limit_defaults_and_validates(self):
        self.assertEqual(self.ctl.normalize_config({})["fps_limit"], 30)
        for good in (10, 30, 60, "45"):
            self.assertEqual(self.ctl.normalize_config({"fps_limit": good})["fps_limit"], int(good))
        for bad in (0, 9, 61, True, 30.5, "fast", None):
            self.assertEqual(self.ctl.normalize_config({"fps_limit": bad})["fps_limit"], 30,
                             f"accepted fps_limit={bad!r}")
        self.ctl.config_store.save_config(self.cfg_path, fps_limit=45)
        self.assertEqual(self.ctl.load_config()["fps_limit"], 45)

    def test_lock_after_seconds_zero_ok(self):
        cfg = self.ctl.normalize_config({"lock_after_seconds": 0})
        self.assertEqual(cfg["lock_after_seconds"], 0)

    def test_lock_after_rejects_bool(self):
        cfg = self.ctl.normalize_config({"lock_after_seconds": True})
        self.assertEqual(cfg["lock_after_seconds"], 300)

    def test_clock_overlay_options_are_validated_and_persisted(self):
        defaults = self.ctl.normalize_config({})
        self.assertFalse(defaults["clock_overlay"])
        self.assertEqual(defaults["clock_overlay_position"], "bottom-right")
        self.assertEqual(defaults["clock_overlay_opacity"], 80)
        for position in ("top-left", "top-right", "bottom-left", "bottom-right"):
            self.assertEqual(self.ctl.normalize_config({"clock_overlay_position": position})["clock_overlay_position"], position)
        for bad in ("center", "../top-left", None, 2):
            self.assertEqual(self.ctl.normalize_config({"clock_overlay_position": bad})["clock_overlay_position"], "bottom-right")
        for opacity in (20, 80, 100):
            self.assertEqual(self.ctl.normalize_config({"clock_overlay_opacity": opacity})["clock_overlay_opacity"], opacity)
        for bad in (19, 101, True, 80.5, "high", None):
            self.assertEqual(self.ctl.normalize_config({"clock_overlay_opacity": bad})["clock_overlay_opacity"], 80)
        for bad in (1, 0, "true", None):
            self.assertFalse(self.ctl.normalize_config({"clock_overlay": bad})["clock_overlay"])
        self.assertTrue(self.ctl.normalize_config({"clock_overlay": True})["clock_overlay"])

    def test_clock_format_whitelist(self):
        for good in ("12h", "24h"):
            self.assertEqual(self.ctl.normalize_config({"clock_format": good})["clock_format"], good)
        for bad in ("12H", "24", "military", None, 12):
            self.assertEqual(self.ctl.normalize_config({"clock_format": bad})["clock_format"], "24h",
                             f"accepted clock_format={bad!r}")

    def test_monitor_identifier_prefers_connector_and_falls_back_stably(self):
        class Geometry:
            x, y, width, height = 0, 0, 1920, 1080

        class ConnectorMonitor:
            def get_connector(self):
                return "HDMI-1"

            def get_model(self):
                return "Panel"

            def get_geometry(self):
                return Geometry()

        class FallbackMonitor:
            def get_connector(self):
                return None

            def get_model(self):
                return "Panel"

            def get_geometry(self):
                return Geometry()

        self.assertEqual(
            self.ctl.config_store.monitor_identifier(ConnectorMonitor(), 0),
            "connector:HDMI-1",
        )
        self.assertEqual(
            self.ctl.config_store.monitor_identifier(FallbackMonitor(), 0),
            "model:Panel|geometry:0,0,1920,1080",
        )

    def test_monitor_assignments_are_sanitized_and_resolve_with_fallback(self):
        cfg = self.ctl.normalize_config({
            "monitor_screensavers": {
                "connector:HDMI-1": "starfield.html",
                "connector:DP-1": "../outside.html",
                "": "blob.html",
                "x" * 201: "blob.html",
                "connector:DP-2": 42,
            }
        })
        self.assertEqual(cfg["monitor_screensavers"], {"connector:HDMI-1": "starfield.html"})
        available = {"starfield.html": "/scenes/starfield.html", "blob.html": "/scenes/blob.html"}
        self.assertEqual(
            self.ctl.config_store.resolve_monitor_scene(
                "connector:HDMI-1", cfg["monitor_screensavers"], available, "blob.html"
            ),
            "starfield.html",
        )
        self.assertEqual(
            self.ctl.config_store.resolve_monitor_scene(
                "connector:DP-1", cfg["monitor_screensavers"], available, "blob.html"
            ),
            "blob.html",
        )
        self.assertEqual(
            self.ctl.config_store.resolve_monitor_scene(
                "connector:HDMI-1", cfg["monitor_screensavers"], {"blob.html": "/scenes/blob.html"}, "blob.html"
            ),
            "blob.html",
        )

    def test_per_scene_options_default_validate_and_persist(self):
        self.assertEqual(
            self.ctl.config_store.get_scene_options({}, "starfield.html"),
            {"speed": 1.0},
        )
        normalized = self.ctl.normalize_config({
            "screensaver_options": {
                "starfield.html": {"speed": 1.7},
                "blob.html": {"speed": 1.8},
                "../starfield.html": {"speed": 1.5},
            }
        })
        self.assertEqual(
            normalized["screensaver_options"], {"starfield.html": {"speed": 1.7}}
        )
        for bad in (True, "fast", 0.1, 5.0, float("nan"), 10 ** 400):
            cfg = self.ctl.normalize_config({
                "screensaver_options": {"starfield.html": {"speed": bad}}
            })
            self.assertEqual(cfg["screensaver_options"], {})
            self.assertEqual(
                self.ctl.config_store.get_scene_options(cfg, "starfield.html"),
                {"speed": 1.0},
            )
        self.ctl.config_store.save_config(
            self.cfg_path,
            screensaver_options={"starfield.html": {"speed": 1.6}},
        )
        self.assertEqual(
            self.ctl.load_config()["screensaver_options"],
            {"starfield.html": {"speed": 1.6}},
        )

    def test_lock_message_is_plain_text_bounded_and_defaults_empty(self):
        self.assertEqual(self.ctl.normalize_config({})["lock_message"], "")
        raw = "  Back at 15:00" + chr(10) + "<script>alert(1)</script>  " + ("x" * 200)
        cfg = self.ctl.normalize_config({"lock_message": raw})
        self.assertEqual(len(cfg["lock_message"]), 160)
        self.assertNotIn(chr(10), cfg["lock_message"])
        self.assertEqual(self.ctl.normalize_config({"lock_message": 123})["lock_message"], "")

    def test_lock_message_set_and_clear_persist(self):
        self.assertEqual(self.ctl.update_lock_message("  Back at 15:00  "), "Back at 15:00")
        self.assertEqual(self.ctl.load_config()["lock_message"], "Back at 15:00")
        self.assertEqual(self.ctl.update_lock_message(""), "")
        self.assertEqual(self.ctl.load_config()["lock_message"], "")

    def test_lock_message_rejects_non_text(self):
        with self.assertRaises(ValueError):
            self.ctl.update_lock_message(None)

    def test_favorites_accept_unique_safe_html_filenames_only(self):
        self.assertEqual(self.ctl.normalize_config({})["favorites"], [])
        cfg = self.ctl.normalize_config({
            "favorites": ["blob.html", "starfield.html", "blob.html", "../secret.html", 12, ""]
        })
        self.assertEqual(cfg["favorites"], ["blob.html", "starfield.html"])

    def test_favorites_roundtrip_through_config_file(self):
        self.ctl.CONFIG_PATH = self.cfg_path
        self.ctl.config_store.save_config(self.cfg_path, favorites=["blob.html", "sakura.html"])
        self.assertEqual(self.ctl.load_config()["favorites"], ["blob.html", "sakura.html"])

    def test_matugen_path_requires_absolute_nonempty_string(self):
        default = self.ctl.DEFAULT_MATUGEN_COLORS_PATH
        self.assertEqual(self.ctl.normalize_config({})["matugen_colors_path"], default)
        for bad in ("", "relative.css", None, 12):
            self.assertEqual(
                self.ctl.normalize_config({"matugen_colors_path": bad})["matugen_colors_path"],
                default,
                f"accepted invalid Matugen path {bad!r}",
            )
        self.assertEqual(
            self.ctl.normalize_config({"matugen_colors_path": "/tmp/custom-colors.css"})["matugen_colors_path"],
            "/tmp/custom-colors.css",
        )

    def test_matugen_path_roundtrips_config_file(self):
        self.write_config({"matugen_colors_path": "/tmp/custom-colors.css"})
        self.assertEqual(self.ctl.load_config()["matugen_colors_path"], "/tmp/custom-colors.css")

    def test_matugen_link_tracks_configured_target(self):
        first = os.path.join(self._tmp.name, "first.css")
        second = os.path.join(self._tmp.name, "second.css")
        cfg = dict(self.defaults, matugen_colors_path=first)
        self.assertTrue(self.ctl.sync_matugen_colors_link(cfg))
        link = os.path.join(self.savers_dir, "matugen-colors.css")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), first)
        self.assertTrue(self.ctl.sync_matugen_colors_link(dict(cfg, matugen_colors_path=second)))
        self.assertEqual(os.readlink(link), second)

    def test_matugen_link_does_not_replace_regular_file(self):
        link = os.path.join(self.savers_dir, "matugen-colors.css")
        with open(link, "w", encoding="utf-8") as handle:
            handle.write("user-owned")
        self.assertFalse(self.ctl.sync_matugen_colors_link(
            dict(self.defaults, matugen_colors_path="/tmp/custom-colors.css")
        ))
        with open(link, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "user-owned")

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


class TestSessionLockTransitions(CtlTestCase):
    def test_lock_hides_viewer_and_does_not_rearm_idle_watch(self):
        ctl = self.ctl
        old_locked = ctl._session_locked
        old_showing = ctl._is_showing
        old_is_active = ctl.is_viewer_active
        old_hide = ctl.hide_viewer
        old_switch = ctl._daemon_switch_to_idle_watch
        hidden = []
        rearmed = []
        try:
            ctl._session_locked = False
            ctl._is_showing = True
            ctl.is_viewer_active = lambda: True
            ctl.hide_viewer = lambda: hidden.append(True)
            ctl._daemon_switch_to_idle_watch = lambda: rearmed.append(True)
            ctl._on_screen_saver_active_changed(True)
            self.assertTrue(ctl._session_locked)
            self.assertEqual(hidden, [True])
            self.assertEqual(rearmed, [])
        finally:
            ctl._session_locked = old_locked
            ctl._is_showing = old_showing
            ctl.is_viewer_active = old_is_active
            ctl.hide_viewer = old_hide
            ctl._daemon_switch_to_idle_watch = old_switch

    def test_hooks_are_off_by_default_and_accept_argv_arrays_only(self):
        cfg = self.ctl.normalize_config({})
        self.assertEqual(cfg["lock_hook"], [])
        self.assertEqual(cfg["unlock_hook"], [])
        cfg = self.ctl.normalize_config({
            "lock_hook": ["/usr/bin/playerctl", "pause"],
            "unlock_hook": "playerctl play",
        })
        self.assertEqual(cfg["lock_hook"], ["/usr/bin/playerctl", "pause"])
        self.assertEqual(cfg["unlock_hook"], [])
        for bad in (["playerctl", 3], ["", "pause"], ["playerctl", "pause\0x"], ["playerctl"] * 33):
            self.assertEqual(self.ctl.normalize_config({"lock_hook": bad})["lock_hook"], [])

    def test_hooks_run_once_per_lock_state_transition(self):
        ctl = self.ctl
        old_locked = ctl._session_locked
        old_run_hook = ctl._run_user_hook
        old_switch = ctl._daemon_switch_to_idle_watch
        old_is_active = ctl.is_viewer_active
        old_showing = ctl._is_showing
        events = []
        try:
            ctl._session_locked = False
            ctl._run_user_hook = lambda event: events.append(event)
            ctl._daemon_switch_to_idle_watch = lambda: None
            ctl.is_viewer_active = lambda: False
            ctl._is_showing = False
            ctl._on_screen_saver_active_changed(True)
            ctl._on_screen_saver_active_changed(True)
            ctl._on_screen_saver_active_changed(False)
            ctl._on_screen_saver_active_changed(False)
            self.assertEqual(events, ["lock", "unlock"])
        finally:
            ctl._session_locked = old_locked
            ctl._run_user_hook = old_run_hook
            ctl._daemon_switch_to_idle_watch = old_switch
            ctl.is_viewer_active = old_is_active
            ctl._is_showing = old_showing

    def test_unlock_rearms_idle_watch(self):
        ctl = self.ctl
        old_locked = ctl._session_locked
        old_switch = ctl._daemon_switch_to_idle_watch
        rearmed = []
        try:
            ctl._session_locked = True
            ctl._daemon_switch_to_idle_watch = lambda: rearmed.append(True)
            ctl._on_screen_saver_active_changed(False)
            self.assertFalse(ctl._session_locked)
            self.assertEqual(rearmed, [True])
        finally:
            ctl._session_locked = old_locked
            ctl._daemon_switch_to_idle_watch = old_switch


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