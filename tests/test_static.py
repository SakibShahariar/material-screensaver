"""Static analysis of the screensavers: HTML structure, theming consistency, CSS patterns.

These checks used to live inline in .github/workflows/ci.yml or did not exist at
all (JS syntax). Keeping them here means the exact same assertions run on PRs,
on pushes, and locally via `python3 -m unittest discover -s tests`.
"""
import os
import re
import subprocess
import tempfile
import unittest

import support


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


class TestHtmlBasics(unittest.TestCase):
    def test_repo_count_matches_readme(self):
        if not support.using_default_dir():
            self.skipTest("targeting a non-repo screensaver dir")
        readme = _read(os.path.join(support.REPO_ROOT, "README.md"))
        # Accept the current README's explicit style count and the older
        # "— N total" wording so this test checks content, not prose phrasing.
        m = re.search(r"— (\d+) total\*?\*?\.", readme.replace("**", ""))
        if m is None:
            m = re.search(r"\*\*(\d+) styles\*\*", readme)
        if m is None:
            m = re.search(r"\*\*(\d+) animated scenes\*\*", readme)
        self.assertIsNotNone(m, "README must state the total number of styles")
        self.assertEqual(len(support.html_files()), int(m.group(1)),
                         "screensavers/ count drifted from the count claimed in README")

    def test_at_least_one_screensaver(self):
        self.assertGreaterEqual(len(support.html_files()), 1, "no .html screensavers found")

    def test_shared_helpers_exist(self):
        for h in support.shared_helpers():
            self.assertTrue(os.path.isfile(h), f"missing shared helper {h}")

    def test_scene_template_has_theme_security_and_motion_conventions(self):
        template = _read(os.path.join(support.REPO_ROOT, "docs", "scene-template.html"))
        csp = re.search(
            r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"',
            template,
            re.I,
        )
        self.assertIsNotNone(csp, "scene template must include a restrictive CSP")
        for directive in ("default-src 'none'", "connect-src 'none'", "object-src 'none'", "base-uri 'none'"):
            self.assertIn(directive, csp.group(1))
        self.assertLess(template.index(csp.group(0)), template.index("matugen-colors.css"))
        self.assertIn('href="matugen-colors.css"', template)
        self.assertIn("prefers-reduced-motion: reduce", template)
        self.assertNotIn("https://", template)
        self.assertNotIn("eval(", template)

    def test_required_markers_everywhere(self):
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            with self.subTest(file=name):
                for marker in ("<!DOCTYPE html", "<meta name=\"viewport\"",
                               "matugen-colors.css", "</html>"):
                    self.assertIn(marker.lower(), text.lower(),
                                  f"{name} missing {marker!r}")

    def test_ctl_does_not_silently_swallow_broad_exceptions(self):
        source = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        silent_catches = re.findall(r"except Exception:\s*\n\s*pass\b", source)
        # The debug logger itself must remain best-effort to avoid recursive logging.
        self.assertLessEqual(len(silent_catches), 1, "unexpected silent broad exception handlers")

    def test_lifecycle_events_are_journal_visible_and_avoid_hook_contents(self):
        source = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        for event in (
            "inhibit_acquired", "inhibit_released", "inhibit_unavailable", "viewer_spawned", "viewer_exit",
            "idle_watch_registered", "active_watch_registered",
            "session_lock_detected", "session_unlocked", "lock_monitor_failed",
            "lock_timer_fired", "session_lock_succeeded", "session_lock_failed",
            "hook_started", "hook_completed", "hook_failed",
        ):
            self.assertIn(f'"{event}"', source)
        self.assertIn("def _log_event(event, **fields):", source)
        self.assertIn("error=type(exc).__name__", source)

    def test_screensavers_have_restrictive_csp_before_resources(self):
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            match = re.search(
                r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"',
                text,
                re.I,
            )
            with self.subTest(file=name):
                self.assertIsNotNone(match, f"{name}: missing Content Security Policy")
                policy = match.group(1)
                for directive in (
                    "default-src 'none'",
                    "script-src 'self' 'unsafe-inline'",
                    "style-src 'self' 'unsafe-inline'",
                    "img-src 'self' data:",
                    "font-src 'self' data:",
                    "connect-src 'none'",
                    "object-src 'none'",
                    "base-uri 'none'",
                ):
                    self.assertIn(directive, policy, f"{name}: CSP missing {directive}")
                self.assertNotIn("file:", policy, f"{name}: CSP allows broad file: resources")
                self.assertLess(text.index(match.group(0)), text.index("matugen-colors.css"),
                                f"{name}: CSP appears after stylesheet resource")

    def test_script_tags_balanced(self):
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            with self.subTest(file=name):
                self.assertEqual(text.count("<script"), text.count("</script>"),
                                 f"{name}: <script> open/close mismatch")

    def test_no_external_cdn(self):
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            with self.subTest(file=name):
                self.assertIsNone(support.CDN_RE.search(text),
                                  f"{name}: external CDN reference")

    def test_no_script_tag_attributes(self):
        # Styles must be self-contained inline scripts; a stray `<script src=...>`
        # for a non-bundled file breaks the "no network" guarantee.
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            with self.subTest(file=name):
                self.assertEqual(re.findall(r"<script\s+[^>]*>", text), [],
                                 f"{name}: script tag carries attributes (external src?)")


class TestThemeConsistency(unittest.TestCase):
    """The screensaver's whole point is live matugen theming — verity every
    style can actually resolve the palette it claims to use."""

    def test_preview_and_viewer_share_restricted_local_file_policy(self):
        gui = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-gui.py"))
        ctl = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        for flag in ("set_allow_file_access_from_file_urls", "set_allow_universal_access_from_file_urls"):
            with self.subTest(flag=flag):
                self.assertIn(f"{flag}(False)", gui)
                self.assertIn(f"{flag}(False)", ctl)
                self.assertNotIn(f"{flag}(True)", gui)
                self.assertNotIn(f"{flag}(True)", ctl)
        self.assertIn("sync_matugen_colors_link(cfg)", gui)
        self.assertIn("sync_matugen_colors_link(cfg)", ctl)

    def test_starfield_speed_query_parameter_is_bounded(self):
        text = _read(os.path.join(support.REPO_ROOT, "screensavers", "starfield.html"))
        self.assertIn('new URLSearchParams(window.location.search).get("speed")', text)
        self.assertIn("Math.min(2, Math.max(0.5, requestedSpeed))", text)
        self.assertIn("320 * speedMul", text)

    def test_missing_matugen_file_has_inline_palette_fallback(self):
        # Each scene ships default CSS variables, so an absent or broken
        # matugen-colors.css symlink does not leave the page unthemed.
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            root = re.search(r":root\s*\{([^}]*)\}", text, re.I | re.S)
            with self.subTest(file=name):
                self.assertIsNotNone(root, f"{name}: no inline :root palette fallback")
                self.assertRegex(
                    root.group(1),
                    r"--[\w-]+\s*:\s*(?:#[0-9a-f]{3,8}\b|rgb|rgba|[0-9])",
                    f"{name}: no concrete inline CSS variable fallback",
                )

    def test_clock_overlay_is_optional_safe_and_non_interactive(self):
        source = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        self.assertIn("material-screensaver-clock-overlay", source)
        self.assertIn("clock_overlay_position", source)
        self.assertIn("clock_overlay_opacity", source)
        self.assertIn("pointer-events:none", source)
        self.assertIn("[id*=\"clock\" i]", source)
        self.assertIn("if (clockLike) return;", source)
        self.assertIn("Decide whether to add the overlay from the rendered DOM", source)
        self.assertIn("if (clockLike) return;", source)
        self.assertNotIn('scene_has_shared_clock = "clock-shared.js" in scene_source', source)

    def test_clock_shared_referenced(self):
        # Every style renders a clock; each must at least reference the helper
        # (loaded dynamically at runtime, so check the string reference).
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            with self.subTest(file=name):
                self.assertIn("clock-shared.js", text, f"{name}: no clock-shared.js reference")

    def test_startclock_requires_clock_helper_or_fallback(self):
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            with self.subTest(file=name):
                if "startClock" in text or "formatClock" in text or "pad2(" in text:
                    self.assertTrue(
                        re.search(r"clock-shared\.js|fallbackClock", text),
                        f"{name}: calls clock helper API but neither references "
                        "clock-shared.js nor defines a fallback")

    def test_theme_helper_api_needs_theme_shared(self):
        # loadThemePalette exists ONLY in theme-shared.js. Using it without
        # either loading the helper or defining a local readRGB crashes at runtime.
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            with self.subTest(file=name):
                if "loadThemePalette" in text:
                    for marker in ("theme-shared.js", "function readRGB"):
                        if marker in text:
                            break
                    else:
                        self.fail(f"{name}: uses loadThemePalette (theme-shared only) "
                                  "with no helper reference")

    def test_readrgb_defined_or_helper_loaded(self):
        # A style that calls readRGB(...) but defines no local copy and loads
        # no theme helper would crash on first paint.
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            with self.subTest(file=name):
                calls_read = "readRGB(" in text
                if calls_read:
                    self.assertTrue(
                        "function readRGB" in text or "theme-shared.js" in text,
                        f"{name}: calls readRGB() but never defines it nor loads theme-shared.js")

    def test_rgb_var_alpha_syntax_valid(self):
        # `rgba(var(--x), 0.5)` and `rgb(var(--x), 0.5)` are zero new async color syntax.
        bad = []
        for path in support.html_files():
            text = _read(path)
            if support.RGBA_VAR_RE.search(text) or support.RGB_VAR_COMMA_RE.search(text):
                bad.append(os.path.basename(path))
        self.assertEqual(bad, [], "invalid var() alpha syntax in: " + ", ".join(bad))


class TestJsSyntax(unittest.TestCase):
    NODE = os.environ.get("MS_TEST_NODE", None)

    @classmethod
    def setUpClass(cls):
        if cls.NODE:
            return
        found = None
        for cand in ("node", "nodejs"):
            try:
                r = subprocess.run(["sh", "-c", f"command -v {cand}"], capture_output=True, text=True)
                if r.returncode == 0 and r.stdout.strip():
                    found = r.stdout.strip()
                    break
            except Exception:
                continue
        cls.NODE = found
        if cls.NODE is None:
            raise unittest.SkipTest("node not available; JS syntax checks skipped")

    def _check(self, js, label):
        if not js.strip():
            return
        fd, tmp = tempfile.mkstemp(suffix=".js")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(js)
            r = subprocess.run([self.NODE, "--check", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                last = r.stderr.strip().splitlines()
                self.fail(f"{label}: JS syntax error\n" + "\n".join(last[-8:]))
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def test_daemon_refreshes_idle_watch_when_config_changes(self):
        source = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        self.assertIn("def check_idle_config()", source)
        self.assertIn("GLib.timeout_add_seconds(2, check_idle_config)", source)
        self.assertIn("def _idle_watch_needs_refresh(", source)
        self.assertIn("return current_idle_seconds != last_idle_seconds or watch_id is None", source)
        self.assertIn("viewer_active=False", source)
        self.assertIn("session_locked=False", source)
        self.assertIn("viewer_active=is_viewer_active()", source)
        self.assertIn("session_locked=_session_locked", source)
        self.assertIn('print(f"Failed to refresh idle timeout: {exc}"', source)

    def test_config_backup_validates_import_and_omits_sensitive_fields(self):
        gui = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-gui.py"))
        self.assertIn('"format": "material-screensaver-config"', gui)
        self.assertIn('payload.get("version") != 1', gui)
        self.assertIn('payload.get("settings"), dict', gui)
        self.assertIn('confirm = Adw.MessageDialog.new(', gui)
        self.assertIn('confirm.add_response("import", "Import")', gui)
        self.assertIn("Hook commands", gui)
        self.assertIn("lock message text", gui)
        self.assertIn("Matugen path", gui)
        # Sensitive values are omitted from the serialized payload; their
        # preservation is documented in the import confirmation text.
        export_start = gui.index('payload = {')
        export_end = gui.index('try:', export_start)
        exported_block = gui[export_start:export_end]
        for sensitive in ('"lock_hook"', '"unlock_hook"', '"lock_message"', '"matugen_colors_path"'):
            self.assertNotIn(sensitive, exported_block)

    def test_scene_favorite_toggle_persists_and_refreshes_picker(self):
        gui = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-gui.py"))
        self.assertIn('self.favorite_button.connect("clicked", self.on_toggle_favorite)', gui)
        self.assertIn('self.favorite_button.set_label("★ Remove from favorites" if is_favorite else "☆ Add to favorites")', gui)
        self.assertIn('favorites.append(self.selected_scene)', gui)
        self.assertIn('self._save_config(favorites=favorites)', gui)
        self.assertIn('self._rebuild_screensaver_picker(self.selected_scene)', gui)
        self.assertIn('favorites_only=self.favorites_only_switch.get_active()', gui)

    def test_failed_scene_shows_safe_fallback_and_logs_scene_name(self):
        source = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        self.assertIn('web.connect("load-failed", on_scene_load_failed)', source)
        self.assertIn('"scene_load_failed"', source)
        self.assertIn('scene=os.path.basename(monitor_html_path)', source)
        self.assertIn('error=type(error).__name__', source)
        self.assertIn('web.load_html(fallback_html, "about:blank")', source)
        self.assertIn("Scene unavailable", source)
        self.assertIn("Change scenes or restart the viewer", source)
        self.assertIn('if scene_load_failed["shown"]:', source)

    def test_display_blanking_is_configurable_and_stops_scene_scripts(self):
        ctl = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        gui = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-gui.py"))
        self.assertIn('blank_minutes = cfg.get("blank_display_after_minutes", 0)', ctl)
        self.assertIn("if blank_minutes > 0:", ctl)
        self.assertIn("window.setTimeout(() => {", ctl)
        self.assertIn("document.open();", ctl)
        self.assertIn("document.write(", ctl)
        self.assertIn("background:#000", ctl)
        self.assertIn('self.blank_display_row.set_title("Blank display after")', gui)
        self.assertIn('self.blank_display_row.connect("notify::value", self.on_blank_display_changed)', gui)

    def test_battery_fps_saver_uses_upower_and_respects_setting(self):
        source = open(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"), encoding="utf-8").read()
        self.assertIn("def _battery_is_discharging():", source)
        self.assertIn('["upower", "-i", "/org/freedesktop/UPower/devices/DisplayDevice"]', source)
        self.assertIn("min(fps_limit, 15)", source)
        self.assertIn('viewer_cfg.get("reduce_fps_on_battery", True)', source)

    def test_reduced_motion_caps_global_frame_rate(self):
        source = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        self.assertIn('window.matchMedia("(prefers-reduced-motion: reduce)")', source)
        self.assertIn("Math.min(requestedLimit, 10)", source)
        readme = _read(os.path.join(support.REPO_ROOT, "README.md"))
        self.assertIn("requestAnimationFrame-driven scenes at **10 FPS**", readme)

    def test_fps_throttle_preserves_cancel_and_limits_callbacks(self):
        source = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        match = re.search(
            r'fps_script = """(.*?)""".replace\("__FPS_LIMIT__", str\(fps_limit\)\)',
            source,
            re.S,
        )
        self.assertIsNotNone(match, "viewer FPS throttle script missing")
        throttle = match.group(1).replace("__FPS_LIMIT__", "30")
        harness = r"""
const nativeFrames = [];
global.window = {
  requestAnimationFrame(callback) { nativeFrames.push(callback); return nativeFrames.length; },
  cancelAnimationFrame() {},
};
""" + throttle + r"""
const delivered = [];
const cancelledId = window.requestAnimationFrame(() => delivered.push("cancelled"));
window.cancelAnimationFrame(cancelledId);
const firstId = window.requestAnimationFrame(timestamp => delivered.push(timestamp));
if (nativeFrames.length !== 1) throw new Error("scheduler did not coalesce native frames");
nativeFrames.shift()(0);
if (delivered.length !== 1 || delivered[0] !== 0) throw new Error("first frame was not delivered");
window.requestAnimationFrame(timestamp => delivered.push(timestamp));
nativeFrames.shift()(10);
if (delivered.length !== 1) throw new Error("frame cap did not defer an early callback");
nativeFrames.shift()(34);
if (delivered.length !== 2 || delivered[1] !== 34) throw new Error("deferred callback was not delivered");
window.cancelAnimationFrame(firstId);
"""
        fd, tmp = tempfile.mkstemp(suffix=".js")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(harness)
            result = subprocess.run([self.NODE, tmp], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr.strip())
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def test_viewer_disables_cross_origin_file_url_access(self):
        source = _read(os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py"))
        self.assertIn("set_allow_universal_access_from_file_urls(False)", source)
        self.assertNotIn("set_allow_universal_access_from_file_urls(True)", source)
        self.assertIn("set_allow_file_access_from_file_urls(False)", source)
        self.assertNotIn("set_allow_file_access_from_file_urls(True)", source)

    def test_shared_clock_uses_runtime_locale_for_date(self):
        text = _read(os.path.join(support.REPO_ROOT, "screensavers", "clock-shared.js"))
        self.assertIn("new Intl.DateTimeFormat(undefined", text)
        self.assertIn("weekday: 'short'", text)
        self.assertIn("month: 'short'", text)
        self.assertNotIn("const days = ['Sun'", text)

    def test_solar_system_fallback_respects_clock_format(self):
        text = _read(os.path.join(support.REPO_ROOT, "screensavers", "solar-system.html"))
        start = text.index("function fallbackClock()")
        end = text.index("\n}", start) + 2
        fallback = text[start:end]
        self.assertIn('new URLSearchParams(location.search).get("format") === "12h"', fallback)
        self.assertIn('use12h ? h : String(h).padStart(2, "0")', fallback)
        self.assertIn('(suffix ? `<span class="ampm">${suffix}</span>` : "")', fallback)

    def test_clock_and_theme_helpers_parse(self):
        for path in support.shared_helpers():
            if not os.path.isfile(path):
                continue
            self._check(_read(path), os.path.basename(path))

    def test_inline_scripts_parse(self):
        for path in support.html_files():
            text = _read(path)
            name = os.path.basename(path)
            scripts = support.extract_scripts(text)
            self.assertGreaterEqual(len(scripts), 1, f"{name}: no inline <script>")
            for i, (attrs, body) in enumerate(scripts, 1):
                with self.subTest(file=name, script=f"#{i}"):
                    self._check(body, f"{name} <script #{i}>")


if __name__ == "__main__":
    unittest.main(verbosity=2)