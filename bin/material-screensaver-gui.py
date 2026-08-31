#!/usr/bin/env python3
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
try:
    gi.require_version("WebKit", "6.0")
    from gi.repository import WebKit
    HAS_WEBKIT = True
except Exception:
    WebKit = None
    HAS_WEBKIT = False
from gi.repository import Gtk, Adw, GLib, Gio, Gdk

import os
import sys
import json
import glob
import subprocess
from urllib.parse import urlencode

SCREENSAVER_DIR = os.path.expanduser("~/.local/share/material-screensaver/screensavers")
CONFIG_PATH = os.path.expanduser("~/.config/material-screensaver/config.json")
CTL_SCRIPT = os.path.expanduser("~/.local/bin/material-screensaver-ctl.py")
SERVICE_NAME = "material-screensaver.service"

KEYBINDING_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/material-screensaver/"
KEYBINDING_PARENT_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
KEYBINDING_CHILD_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"


def get_keybinding_settings():
    """Registers our custom keybinding path with GNOME if needed, returns its Settings object."""
    parent = Gio.Settings.new(KEYBINDING_PARENT_SCHEMA)
    paths = parent.get_strv("custom-keybindings")
    if KEYBINDING_PATH not in paths:
        parent.set_strv("custom-keybindings", paths + [KEYBINDING_PATH])
    child = Gio.Settings.new_with_path(KEYBINDING_CHILD_SCHEMA, KEYBINDING_PATH)
    if not child.get_string("command"):
        child.set_string("name", "Material Screensaver")
        child.set_string("command", f"{CTL_SCRIPT} toggle")
    return child

DEFAULT_CONFIG = {"active": None, "idle_seconds": 300, "clock_format": "24h", "random": False, "lock_after_seconds": 300, "close_on_mouse": True}


def _valid_int(value, minimum, maximum):
    if isinstance(value, bool):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if minimum <= value <= maximum else None


def normalize_config(data):
    """Return a complete, safe configuration from user-editable JSON."""
    cfg = dict(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return cfg
    active = data.get("active")
    if active is None or isinstance(active, str):
        cfg["active"] = active
    for key in ("random", "close_on_mouse"):
        if isinstance(data.get(key), bool):
            cfg[key] = data[key]
    idle = _valid_int(data.get("idle_seconds"), 1, 86400)
    if idle is not None:
        cfg["idle_seconds"] = idle
    lock = _valid_int(data.get("lock_after_seconds"), 0, 86400)
    if lock is not None:
        cfg["lock_after_seconds"] = lock
    if data.get("clock_format") in ("12h", "24h"):
        cfg["clock_format"] = data["clock_format"]
    return cfg


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return normalize_config(json.load(f))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return dict(DEFAULT_CONFIG)


def save_config(**updates):
    cfg = load_config()
    cfg.update(updates)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, CONFIG_PATH)
    except Exception:
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def display_name(filename):
    stem = os.path.splitext(filename)[0]
    return stem.replace("-", " ").replace("_", " ").title()


def list_screensavers():
    paths = sorted(glob.glob(os.path.join(SCREENSAVER_DIR, "*.html")))
    return [os.path.basename(p) for p in paths]


class ScreensaverWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Screensaver")
        self.set_default_size(480, 600)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        page = Adw.PreferencesPage()

        # --- Screensaver picker ---
        sv_group = Adw.PreferencesGroup(title="Screensaver")
        page.add(sv_group)

        self.random_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        random_row = Adw.ActionRow(
            title="Random each time",
            subtitle="Pick randomly on every launch",
        )
        random_row.add_suffix(self.random_switch)
        random_row.set_activatable_widget(self.random_switch)
        sv_group.add(random_row)

        self.screensaver_files = list_screensavers()
        self.combo_row = Adw.ComboRow(title="Active screensaver")
        if self.screensaver_files:
            names = Gtk.StringList.new([display_name(f) for f in self.screensaver_files])
            self.combo_row.set_model(names)
        else:
            self.combo_row.set_model(Gtk.StringList.new(["No screensavers found"]))
            self.combo_row.set_sensitive(False)
        sv_group.add(self.combo_row)

        note = Adw.ActionRow(
            title="Add more later",
            subtitle=f"Drop .html files into {SCREENSAVER_DIR}",
        )
        note.add_css_class("dim-label")
        sv_group.add(note)

        # --- Live Preview (WebKit thumbnail) ---
        if HAS_WEBKIT and self.screensaver_files:
            preview_group_live = Adw.PreferencesGroup(title="Live Preview")
            page.add(preview_group_live)
            frame = Gtk.Frame()
            frame.add_css_class("card")
            try:
                frame.set_overflow(Gtk.Overflow.HIDDEN)
            except Exception:
                pass
            self.preview_web = WebKit.WebView()
            self.preview_web.set_size_request(460, 260)
            # reduce resources for thumbnail
            try:
                s = self.preview_web.get_settings()
                s.set_enable_write_console_messages_to_stdout(False)
            except Exception:
                pass
            frame.set_child(self.preview_web)
            # wrap frame in a row-like container for PreferencesGroup
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.append(frame)
            preview_group_live.add(box)
            # overlay label for random
            self._update_preview()
        else:
            self.preview_web = None

        # --- Timing ---
        timing_group = Adw.PreferencesGroup(title="Timing")
        page.add(timing_group)
        self.idle_row = Adw.SpinRow.new_with_range(1, 120, 1)
        self.idle_row.set_title("Idle timeout")
        self.idle_row.set_subtitle("Minutes before auto-launch")
        timing_group.add(self.idle_row)
        self.lock_row = Adw.SpinRow.new_with_range(0, 60, 1)
        self.lock_row.set_title("Lock after")
        self.lock_row.set_subtitle("Minutes on screensaver before lock (0 = never)")
        timing_group.add(self.lock_row)

        # --- Interaction ---
        interact_group = Adw.PreferencesGroup(title="Interaction")
        page.add(interact_group)
        self.mouse_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        mouse_row = Adw.ActionRow(title="Close on mouse movement", subtitle="Move mouse to hide (off = key/click only)")
        mouse_row.add_suffix(self.mouse_switch)
        mouse_row.set_activatable_widget(self.mouse_switch)
        interact_group.add(mouse_row)

        # --- Clock format ---
        clock_group = Adw.PreferencesGroup(title="Clock")
        page.add(clock_group)
        self.ampm_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        ampm_row = Adw.ActionRow(title="Use 12-hour clock (AM/PM)")
        ampm_row.add_suffix(self.ampm_switch)
        ampm_row.set_activatable_widget(self.ampm_switch)
        clock_group.add(ampm_row)

        # --- Automatic ---
        auto_group = Adw.PreferencesGroup(title="Automatic")
        page.add(auto_group)
        self.autostart_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        autostart_row = Adw.ActionRow(
            title="Run automatically",
            subtitle="Launch when idle (systemd service)",
        )
        autostart_row.add_suffix(self.autostart_switch)
        autostart_row.set_activatable_widget(self.autostart_switch)
        auto_group.add(autostart_row)

        # --- Shortcut ---
        shortcut_group = Adw.PreferencesGroup(title="Keyboard Shortcut")
        page.add(shortcut_group)
        self.shortcut_row = Adw.ActionRow(title="Toggle screensaver")
        change_btn = Gtk.Button(label="Change…", valign=Gtk.Align.CENTER)
        change_btn.connect("clicked", self.on_change_shortcut)
        self.shortcut_row.add_suffix(change_btn)
        shortcut_group.add(self.shortcut_row)

        # --- Preview ---
        preview_group = Adw.PreferencesGroup(title="Preview")
        page.add(preview_group)
        preview_row = Adw.ActionRow(title="Test it now")
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        start_btn = Gtk.Button(label="Start")
        start_btn.add_css_class("suggested-action")
        start_btn.connect("clicked", self.on_start_clicked)
        stop_btn = Gtk.Button(label="Stop")
        stop_btn.connect("clicked", self.on_stop_clicked)
        box.append(start_btn)
        box.append(stop_btn)
        preview_row.add_suffix(box)
        preview_group.add(preview_row)

        toolbar_view.set_content(page)
        self.set_content(toolbar_view)

        self.load_state()

        # connect after loading so initial population doesn't trigger writes
        self.random_switch.connect("notify::active", self.on_random_toggled)
        self.combo_row.connect("notify::selected", self.on_screensaver_changed)
        self.idle_row.connect("notify::value", self.on_idle_changed)
        self.lock_row.connect("notify::value", self.on_lock_changed)
        self.mouse_switch.connect("notify::active", self.on_mouse_toggled)
        self.ampm_switch.connect("notify::active", self.on_ampm_toggled)
        self.autostart_switch.connect("notify::active", self.on_autostart_toggled)

    def load_state(self):
        cfg = load_config()

        is_random = cfg.get("random", False)
        self.random_switch.set_active(is_random)
        self.combo_row.set_sensitive(bool(self.screensaver_files) and not is_random)

        if self.screensaver_files:
            active = cfg.get("active")
            idx = self.screensaver_files.index(active) if active in self.screensaver_files else 0
            self.combo_row.set_selected(idx)

        self.idle_row.set_value(cfg.get("idle_seconds", 300) / 60)
        self.lock_row.set_value(cfg.get("lock_after_seconds", 300) / 60)
        self.mouse_switch.set_active(cfg.get("close_on_mouse", True))

        self.ampm_switch.set_active(cfg.get("clock_format", "24h") == "12h")

        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", SERVICE_NAME],
            capture_output=True, text=True,
        )
        self.autostart_switch.set_active(result.stdout.strip() == "enabled")

        self.refresh_shortcut_label()

    def _update_preview(self):
        if not HAS_WEBKIT or not hasattr(self, "preview_web") or self.preview_web is None:
            return
        # if random, show first file as preview hint
        cfg = load_config()
        if cfg.get("random", False):
            # show a hint that random is on
            try:
                self.preview_web.load_uri("about:blank")
            except Exception:
                pass
            return
        idx = self.combo_row.get_selected()
        if 0 <= idx < len(self.screensaver_files):
            fn = self.screensaver_files[idx]
            path = os.path.join(SCREENSAVER_DIR, fn)
            fmt = cfg.get("clock_format", "24h")
            uri = Gio.File.new_for_path(path).get_uri()
            uri = f"{uri}?{urlencode({'format': fmt})}"
            try:
                self.preview_web.load_uri(uri)
            except Exception:
                pass

    def refresh_shortcut_label(self):
        try:
            binding = get_keybinding_settings().get_string("binding")
        except GLib.Error:
            binding = ""
        if binding:
            ok, keyval, mods = Gtk.accelerator_parse(binding)
            label = Gtk.accelerator_get_label(keyval, mods) if ok else binding
            self.shortcut_row.set_subtitle(label)
        else:
            self.shortcut_row.set_subtitle("Not set")

    def on_change_shortcut(self, _btn):
        dialog = Gtk.Window(transient_for=self, modal=True, title="Set Shortcut")
        dialog.set_default_size(360, 140)
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
            margin_top=28, margin_bottom=28, margin_start=28, margin_end=28,
            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
        )
        title = Gtk.Label(label="Press a key combination…")
        title.add_css_class("title-3")
        box.append(title)
        hint = Gtk.Label(label="Esc to cancel")
        hint.add_css_class("dim-label")
        box.append(hint)
        dialog.set_child(box)

        controller = Gtk.EventControllerKey()

        def on_key(_ctrl, keyval, _keycode, state):
            if keyval == Gdk.KEY_Escape:
                dialog.close()
                return True
            mods = state & Gtk.accelerator_get_default_mod_mask()
            if not Gtk.accelerator_valid(keyval, mods):
                return True  # modifier-only press, keep waiting
            accel = Gtk.accelerator_name(keyval, mods)
            get_keybinding_settings().set_string("binding", accel)
            self.refresh_shortcut_label()
            dialog.close()
            return True

        controller.connect("key-pressed", on_key)
        dialog.add_controller(controller)
        dialog.present()

    def on_random_toggled(self, switch, _pspec):
        is_random = switch.get_active()
        save_config(random=is_random)
        self.combo_row.set_sensitive(bool(self.screensaver_files) and not is_random)
        self._update_preview()

    def on_screensaver_changed(self, row, _pspec):
        idx = row.get_selected()
        if 0 <= idx < len(self.screensaver_files):
            save_config(active=self.screensaver_files[idx])
        self._update_preview()

    def on_idle_changed(self, row, _pspec):
        save_config(idle_seconds=int(row.get_value() * 60))

    def on_lock_changed(self, row, _pspec):
        save_config(lock_after_seconds=int(row.get_value() * 60))

    def on_mouse_toggled(self, switch, _pspec):
        save_config(close_on_mouse=switch.get_active())

    def on_ampm_toggled(self, switch, _pspec):
        save_config(clock_format="12h" if switch.get_active() else "24h")
        self._update_preview()

    def on_autostart_toggled(self, switch, _pspec):
        action = "enable" if switch.get_active() else "disable"
        subprocess.run(["systemctl", "--user", action, "--now", SERVICE_NAME])

    def on_start_clicked(self, _btn):
        subprocess.Popen([CTL_SCRIPT, "start"])

    def on_stop_clicked(self, _btn):
        subprocess.Popen([CTL_SCRIPT, "stop"])


class ScreensaverApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.sakib.MaterialScreensaverSettings")

    def do_activate(self):
        win = self.props.active_window or ScreensaverWindow(self)
        win.present()


if __name__ == "__main__":
    sys.exit(ScreensaverApp().run(sys.argv))
