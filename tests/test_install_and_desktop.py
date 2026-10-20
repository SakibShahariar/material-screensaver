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
        exec_line = m.group(1)
        # Allow %h (systemd-style, expanded at install), sh -c with $HOME,
        # or absolute path – all resolvable via install.sh or shell expansion.
        self.assertTrue(
            exec_line.startswith("%h/.local/bin/material-screensaver-gui.py")
            or "material-screensaver-gui.py" in exec_line and ("$HOME" in exec_line or "%h" in exec_line or exec_line.startswith("sh -c")),
            f"Exec should use resolvable path to gui, got: {exec_line}")
        # TryExec if present must also be resolvable or omitted (no invalid %h without expansion)
        m2 = re.search(r"^TryExec=(.+)$", text, re.M)
        if m2:
            self.assertFalse(m2.group(1).startswith("%h/") and "\\$HOME" not in exec_line,
                             f"TryExec with literal %h hides entry (Exec should expand $HOME): {m2.group(1)}")

    def test_desktop_icon_matches_install_target(self):
        text = self._read("applications/material-screensaver-settings.desktop")
        m = re.search(r"^Icon=(.+)$", text, re.M)
        self.assertEqual(m.group(1).strip() if m else "", "material-screensaver",
                         "desktop Icon= must match installer's icon target basename")

    def test_timing_settings_match_config_seconds(self):
        gui = self._read("bin/material-screensaver-gui.py")
        self.assertIn("Adw.SpinRow.new_with_range(1, 86400, 1)", gui)
        self.assertIn("Adw.SpinRow.new_with_range(0, 86400, 1)", gui)
        self.assertIn('self.idle_row.set_value(cfg.get("idle_seconds", 300))', gui)
        self.assertIn('self.lock_row.set_value(cfg.get("lock_after_seconds", 300))', gui)
        self.assertIn("self._save_config(idle_seconds=int(row.get_value()))", gui)
        self.assertIn("self._save_config(lock_after_seconds=int(row.get_value()))", gui)

    def test_autostart_systemctl_runs_asynchronously_and_reverts_on_failure(self):
        gui = self._read("bin/material-screensaver-gui.py")
        self.assertIn("Gio.Subprocess.new([\"systemctl\", \"--user\", *args]", gui)
        self.assertIn("proc.communicate_utf8_async(None, None, completed)", gui)
        self.assertIn('self._run_systemctl_async(["is-active", SERVICE_NAME], on_active_checked)', gui)
        self.assertIn('subtitle = "Launch when idle (service running)"', gui)
        self.assertIn("switch.set_active(previous)", gui)
        self.assertIn("self.toast_overlay.add_toast(Adw.Toast.new(detail))", gui)
        self.assertNotIn('subprocess.run(["systemctl", "--user", action, "--now", SERVICE_NAME])', gui)

    def test_preview_uses_ephemeral_restricted_webkit_and_suspends(self):
        gui = self._read("bin/material-screensaver-gui.py")
        self.assertIn("WebKit.WebContext.new_ephemeral()", gui)
        self.assertIn("WebKit.WebView.new_with_context(self.preview_context)", gui)
        self.assertIn("settings.set_allow_file_access_from_file_urls(False)", gui)
        self.assertIn("settings.set_allow_universal_access_from_file_urls(False)", gui)
        self.assertIn('self.preview_web.load_uri("about:blank")', gui)
        self.assertIn('self.connect("notify::is-active", self.on_preview_activity_changed)', gui)

    def test_daemon_suppresses_idle_activation_while_locked(self):
        ctl = self._read("bin/material-screensaver-ctl.py")
        self.assertIn("_session_locked = False", ctl)
        self.assertIn("if _session_locked:\n                _dbg(\"idle watch not armed while session is locked\")", ctl)
        self.assertIn("ignored idle WatchFired while session is locked", ctl)
        self.assertIn("remove_watch(\"active\")\n            remove_watch(\"idle\")", ctl)
        self.assertIn("remove_watch(\"idle\")\n            remove_watch(\"active\")", ctl)
        self.assertIn("refused to show viewer while session is locked", ctl)
        self.assertIn("session unlocked; re-arming idle watch", ctl)
        self.assertIn("Unable to monitor GNOME session lock state", ctl)

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
        self.assertIn("51", meta["shell-version"],
                        "gesture guard must declare compatibility with GNOME Shell 51")
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

    def test_install_stages_and_can_restore_previous_screensavers(self):
        sh = self._read_sh()
        self.assertIn('mktemp -d "$DATA_DIR/.screensavers.new.XXXXXX"', sh)
        self.assertIn('BACKUP_DIR="$(mktemp -d "$DATA_DIR/.screensavers.backup.XXXXXX")"', sh)
        self.assertNotIn('BACKUP_DIR="$(mktemp -u ', sh)
        self.assertIn('"$BACKUP_DIR/previous"', sh)
        self.assertIn('mv -- "$SCREENSAVERS_DIR" "$BACKUP_DIR"', sh)
        self.assertIn('mv -- "$BACKUP_DIR/previous" "$SCREENSAVERS_DIR"', sh)
        self.assertNotIn('mv -- "$BACKUP_DIR" "$SCREENSAVERS_DIR"', sh)
        self.assertIn('if [[ "$status" -ne 0 && -d "$SCREENSAVERS_DIR" ]]', sh)
        self.assertIn('systemctl --user start material-screensaver.service', sh)
        self.assertNotIn('rm -rf ~/.local/share/material-screensaver/screensavers', sh)

    def test_uninstall_script_removes_only_project_files(self):
        path = os.path.join(support.REPO_ROOT, "uninstall.sh")
        result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(path, encoding="utf-8") as f:
            sh = f.read()
        self.assertIn("systemctl --user disable --now material-screensaver.service", sh)
        self.assertIn("enabled-extensions", sh)
        self.assertIn('"${DATA_DIR:?}"', sh)
        self.assertNotIn('rm -rf -- "$HOME/.config/material-screensaver"', sh)

    def test_install_sh_copies_and_enables_extension(self):
        text = subprocess.run(["bash", "-n", os.path.join(support.REPO_ROOT, "install.sh")],
                              capture_output=True, text=True)
        self.assertEqual(text.returncode, 0)
        sh = self._read_sh()
        self.assertIn('EXT_BASE="$HOME/.local/share/gnome-shell/extensions"', sh)
        self.assertIn('"${EXT_BASE:?}/$EXT_UUID"', sh)
        self.assertIn("enabled-extensions", sh)

    def _read_sh(self):
        with open(os.path.join(support.REPO_ROOT, "install.sh"), encoding="utf-8") as f:
            return f.read()


if __name__ == "__main__":
    unittest.main(verbosity=2)