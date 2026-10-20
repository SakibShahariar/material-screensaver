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

import argparse
import os
import sys
import json
import material_screensaver_config as config_store
import random
import subprocess
import tempfile
import re
import html as html_lib
from urllib.parse import urlencode

SCREENSAVER_DIR = os.path.expanduser("~/.local/share/material-screensaver/screensavers")
CONFIG_PATH = os.path.expanduser("~/.config/material-screensaver/config.json")
CTL_SCRIPT = os.path.expanduser("~/.local/bin/material-screensaver-ctl.py")
SERVICE_NAME = "material-screensaver.service"
REQUESTED_PREVIEW = None

KEYBINDING_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/material-screensaver/"
KEYBINDING_PARENT_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
KEYBINDING_CHILD_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"


def get_keybinding_settings(create=False):
    """Read our binding without side effects; register it only when explicitly created."""
    parent = Gio.Settings.new(KEYBINDING_PARENT_SCHEMA)
    paths = parent.get_strv("custom-keybindings")
    if KEYBINDING_PATH not in paths:
        if not create:
            return None
        parent.set_strv("custom-keybindings", paths + [KEYBINDING_PATH])
    child = Gio.Settings.new_with_path(KEYBINDING_CHILD_SCHEMA, KEYBINDING_PATH)
    if create and not child.get_string("command"):
        child.set_string("name", "Material Screensaver")
        child.set_string("command", f"{CTL_SCRIPT} toggle")
    return child

DEFAULT_MATUGEN_COLORS_PATH = os.path.expanduser("~/.config/matugen/matugen-colors.css")
DEFAULT_MATUGEN_COLORS_PATH = config_store.DEFAULT_MATUGEN_COLORS_PATH
DEFAULT_CONFIG = config_store.DEFAULT_CONFIG
_valid_int = config_store._valid_int
normalize_config = config_store.normalize_config


def load_config():
    return config_store.load_config(CONFIG_PATH)


def save_config(**updates):
    return config_store.save_config(CONFIG_PATH, **updates)


def sync_matugen_colors_link(cfg=None):
    if not isinstance(cfg, dict):
        cfg = load_config()
    return config_store.sync_matugen_colors_link(SCREENSAVER_DIR, cfg)


def display_name(filename):
    """Prefer the scene's own title; retain a filename fallback for user scenes."""
    stem = os.path.splitext(filename)[0]
    scene_path = os.path.join(SCREENSAVER_DIR, filename)
    try:
        with open(scene_path, encoding="utf-8") as f:
            source = f.read()
        match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", source, re.IGNORECASE | re.DOTALL)
        if match:
            title = html_lib.unescape(re.sub(r"<[^>]*>", "", match.group(1))).strip()
            prefix = "Material Screensaver — "
            if title.lower().startswith(prefix.lower()):
                title = title[len(prefix):].strip()
            # Some older scenes use the filename itself as their HTML title.
            if title and title.casefold() != stem.casefold():
                return title
    except (OSError, UnicodeError):
        pass
    return stem.replace("-", " ").replace("_", " ").title()


def list_screensavers():
    return [os.path.basename(path) for path in config_store.list_screensavers(SCREENSAVER_DIR)]


SCENE_CATEGORIES = {
    "autumnleaves.html": "Nature",
    "blob.html": "Abstract",
    "bounce.html": "Abstract",
    "bubbles.html": "Nature",
    "circuitboard.html": "Geometric",
    "city.html": "Abstract",
    "constellation.html": "Space",
    "cymatics.html": "Generative Art",
    "fireworks.html": "Nature",
    "flow.html": "Generative Art",
    "gameoflife.html": "Generative Art",
    "glitch.html": "Generative Art",
    "kaleidoscope.html": "Geometric",
    "lanterns.html": "Nature",
    "magnetic-field-lines.html": "Space",
    "metaphysical-horizon.html": "Space",
    "n-body-galaxies.html": "Space",
    "organic-harmonic-field.html": "Generative Art",
    "origami.html": "Geometric",
    "papercranes.html": "Geometric",
    "quantum-interference.html": "Space",
    "rain-on-a-window.html": "Nature",
    "rain.html": "Nature",
    "sakura.html": "Nature",
    "soft-body-creatures.html": "Nature",
    "solar-system.html": "Space",
    "starfield.html": "Space",
    "strange-attractor-flow.html": "Generative Art",
    "typewriter.html": "Abstract",
    "voronoi.html": "Geometric",
    "wave-function-collapse.html": "Generative Art",
}
CATEGORY_OPTIONS = [
    "All categories", "Space", "Nature", "Generative Art",
    "Geometric", "Abstract", "Other",
]


def filter_screensavers(filenames, query="", category="All categories",
                        favorites=(), favorites_only=False):
    """Filter scene filenames without changing selection or persisted config."""
    query = (query or "").strip().casefold()
    favorites = favorites if isinstance(favorites, (list, tuple, set)) else ()
    favorite_names = {
        name for name in favorites if isinstance(name, str)
    }
    if category not in CATEGORY_OPTIONS:
        category = "All categories"
    result = []
    for filename in filenames:
        if query and query not in filename.casefold() and query not in display_name(filename).casefold():
            continue
        if category != "All categories" and SCENE_CATEGORIES.get(filename, "Other") != category:
            continue
        if favorites_only and filename not in favorite_names:
            continue
        result.append(filename)
    return result


class ScreensaverWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Screensaver")
        self._preview_override = REQUESTED_PREVIEW
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

        self.search_entry = Gtk.SearchEntry(hexpand=True)
        self.search_entry.set_placeholder_text("Search scenes by name")
        search_row = Adw.ActionRow(title="Search")
        search_row.add_suffix(self.search_entry)
        sv_group.add(search_row)

        self.category_row = Adw.ComboRow(title="Category")
        self.category_row.set_model(Gtk.StringList.new(CATEGORY_OPTIONS))
        sv_group.add(self.category_row)

        self.favorites_only_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        favorites_only_row = Adw.ActionRow(
            title="Favorites only",
            subtitle="Filter the picker to saved favorites",
        )
        favorites_only_row.add_suffix(self.favorites_only_switch)
        favorites_only_row.set_activatable_widget(self.favorites_only_switch)
        sv_group.add(favorites_only_row)

        self.favorite_button = Gtk.Button(label="☆ Add to favorites", valign=Gtk.Align.CENTER)
        favorite_row = Adw.ActionRow(
            title="Selected scene",
            subtitle="Save or remove the selected scene from favorites",
        )
        favorite_row.add_suffix(self.favorite_button)
        sv_group.add(favorite_row)

        self.screensaver_files = list_screensavers()
        self.filtered_screensaver_files = list(self.screensaver_files)
        self.selected_scene = None
        self._picker_updating = False
        self.combo_row = Adw.ComboRow(title="Active screensaver")
        if self.screensaver_files:
            names = Gtk.StringList.new([display_name(f) for f in self.screensaver_files])
            self.combo_row.set_model(names)
        else:
            self.combo_row.set_model(Gtk.StringList.new(["No screensavers found"]))
            self.combo_row.set_sensitive(False)
        sv_group.add(self.combo_row)

        self.monitor_assignment_group = Adw.PreferencesGroup(title="Per-monitor screensavers")
        page.add(self.monitor_assignment_group)
        self.monitor_assignment_rows = {}

        note = Adw.ActionRow(
            title="Add more later",
            subtitle=f"Drop .html files into {SCREENSAVER_DIR}",
        )
        note.add_css_class("dim-label")
        sv_group.add(note)

        # --- Per-scene customization ---
        self.customization_group = Adw.PreferencesGroup(title="Customize selected scene")
        page.add(self.customization_group)
        self.scene_option_rows = {}
        self.scene_option_specs = {}
        for scene_name, option_specs in config_store.SCENE_OPTION_SCHEMA.items():
            for option_name, spec in option_specs.items():
                row = Adw.SpinRow.new_with_range(spec["min"], spec["max"], spec["step"])
                row.set_digits(1 if spec["step"] < 1 else 0)
                row.set_title(spec["label"])
                row.set_subtitle(f"Default: {spec['default']}")
                self.customization_group.add(row)
                self.scene_option_rows[(scene_name, option_name)] = row
                self.scene_option_specs[(scene_name, option_name)] = spec

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
            # Use an ephemeral WebKit session like the fullscreen viewer, and
            # keep local-file permissions aligned with the production renderer.
            try:
                self.preview_context = WebKit.WebContext.new_ephemeral()
                try:
                    self.preview_context.set_cache_model(WebKit.CacheModel.DOCUMENT_VIEWER)
                except Exception:
                    pass
                self.preview_web = WebKit.WebView.new_with_context(self.preview_context)
            except Exception:
                self.preview_context = None
                self.preview_web = WebKit.WebView()
            self.preview_web.set_size_request(460, 260)
            try:
                settings = self.preview_web.get_settings()
                settings.set_allow_file_access_from_file_urls(False)
                settings.set_allow_universal_access_from_file_urls(False)
                settings.set_enable_write_console_messages_to_stdout(False)
                settings.set_enable_javascript(True)
            except Exception as exc:
                print(f"Could not configure preview WebKit security: {exc}", file=sys.stderr)
            frame.set_child(self.preview_web)
            click = Gtk.GestureClick()
            click.connect("pressed", lambda *_: self._update_preview())
            self.preview_web.add_controller(click)
            # wrap frame in a row-like container for PreferencesGroup
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.append(frame)
            hint = Gtk.Label(label="Click the preview to refresh (shuffles in random mode)")
            hint.add_css_class("caption")
            hint.add_css_class("dim-label")
            hint.set_margin_top(6)
            box.append(hint)
            preview_group_live.add(box)
            self._update_preview()
        else:
            self.preview_web = None

        # --- Timing ---
        timing_group = Adw.PreferencesGroup(title="Timing")
        page.add(timing_group)
        # Config stores seconds (idle: 1 second–24 hours; lock: 0–24 hours).
        # Use seconds in the UI so valid hand-edited values are not rounded or
        # clamped when the Settings window is opened and saved again.
        self.idle_row = Adw.SpinRow.new_with_range(1, 86400, 1)
        self.idle_row.set_digits(0)
        self.idle_row.set_title("Idle timeout")
        self.idle_row.set_subtitle("Seconds before auto-launch (1–86,400)")
        timing_group.add(self.idle_row)
        self.lock_row = Adw.SpinRow.new_with_range(0, 86400, 1)
        self.lock_row.set_digits(0)
        self.lock_row.set_title("Lock after")
        self.lock_row.set_subtitle("Seconds on screensaver before lock (0 = never; max 86,400)")
        timing_group.add(self.lock_row)
        self.fps_row = Adw.SpinRow.new_with_range(10, 60, 5)
        self.fps_row.set_digits(0)
        self.fps_row.set_title("Animation frame-rate cap")
        self.fps_row.set_subtitle("Limit requestAnimationFrame scenes to 10–60 FPS (default 30)")
        timing_group.add(self.fps_row)
        self.blank_display_row = Adw.SpinRow.new_with_range(0, 1440, 1)
        self.blank_display_row.set_digits(0)
        self.blank_display_row.set_title("Blank display after")
        self.blank_display_row.set_subtitle("Minutes after the screensaver starts (0 = never; max 1,440)")
        timing_group.add(self.blank_display_row)

        # --- Clock format ---
        clock_group = Adw.PreferencesGroup(title="Clock")
        page.add(clock_group)
        self.ampm_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        ampm_row = Adw.ActionRow(title="Use 12-hour clock (AM/PM)")
        ampm_row.add_suffix(self.ampm_switch)
        ampm_row.set_activatable_widget(self.ampm_switch)
        clock_group.add(ampm_row)
        self.clock_overlay_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        overlay_row = Adw.ActionRow(
            title="Show clock overlay when a scene has no clock",
            subtitle="Automatically skips scenes with a detected clock or date",
        )
        overlay_row.add_suffix(self.clock_overlay_switch)
        overlay_row.set_activatable_widget(self.clock_overlay_switch)
        clock_group.add(overlay_row)
        self.clock_overlay_positions = ["top-left", "top-right", "bottom-left", "bottom-right"]
        self.clock_overlay_position_row = Adw.ComboRow(title="Overlay position")
        self.clock_overlay_position_row.set_model(Gtk.StringList.new(["Top left", "Top right", "Bottom left", "Bottom right"]))
        clock_group.add(self.clock_overlay_position_row)
        self.clock_overlay_opacity_row = Adw.SpinRow.new_with_range(20, 100, 5)
        self.clock_overlay_opacity_row.set_digits(0)
        self.clock_overlay_opacity_row.set_title("Overlay opacity (%)")
        self.clock_overlay_opacity_row.set_subtitle("20%–100% opacity")
        clock_group.add(self.clock_overlay_opacity_row)

        # --- Matugen palette ---
        matugen_group = Adw.PreferencesGroup(title="Matugen")
        page.add(matugen_group)
        matugen_row = Adw.ActionRow(
            title="Colors stylesheet",
            subtitle="Absolute path to Matugen's generated CSS file",
        )
        self.matugen_path_entry = Gtk.Entry(hexpand=True)
        self.matugen_path_entry.set_width_chars(24)
        self.matugen_path_entry.set_placeholder_text(DEFAULT_MATUGEN_COLORS_PATH)
        matugen_row.add_suffix(self.matugen_path_entry)
        self.matugen_path_apply = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
        self.matugen_path_apply.connect("clicked", self.on_matugen_path_apply)
        matugen_row.add_suffix(self.matugen_path_apply)
        matugen_group.add(matugen_row)

        # --- Optional lock message ---
        message_group = Adw.PreferencesGroup(title="Lock message")
        page.add(message_group)
        message_row = Adw.ActionRow(
            title="Message shown over the screensaver",
            subtitle="Optional plain text, up to 160 characters; visible to anyone nearby",
        )
        self.lock_message_entry = Gtk.Entry(hexpand=True)
        self.lock_message_entry.set_width_chars(24)
        self.lock_message_entry.set_placeholder_text("Back at 15:00")
        message_row.add_suffix(self.lock_message_entry)
        self.lock_message_apply = Gtk.Button(label="Save", valign=Gtk.Align.CENTER)
        self.lock_message_apply.connect("clicked", self.on_lock_message_apply)
        message_row.add_suffix(self.lock_message_apply)
        self.lock_message_clear = Gtk.Button(label="Clear", valign=Gtk.Align.CENTER)
        self.lock_message_clear.connect("clicked", self.on_lock_message_clear)
        message_row.add_suffix(self.lock_message_clear)
        message_group.add(message_row)

        # --- Automatic ---
        auto_group = Adw.PreferencesGroup(title="Automatic")
        page.add(auto_group)
        self.autostart_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.autostart_row = Adw.ActionRow(
            title="Run automatically",
            subtitle="Launch when idle (checking service state…)",
        )
        autostart_row = self.autostart_row
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
        self.clear_shortcut_button = Gtk.Button(label="Clear", valign=Gtk.Align.CENTER)
        self.clear_shortcut_button.connect("clicked", self.on_clear_shortcut)
        self.shortcut_row.add_suffix(self.clear_shortcut_button)
        shortcut_group.add(self.shortcut_row)

        toolbar_view.set_content(page)
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(toolbar_view)
        self.set_content(self.toast_overlay)

        self.load_state()
        self.connect("notify::is-active", self.on_preview_activity_changed)

        # connect after loading so initial population doesn't trigger writes
        self.random_switch.connect("notify::active", self.on_random_toggled)
        self.combo_row.connect("notify::selected", self.on_screensaver_changed)
        self.idle_row.connect("notify::value", self.on_idle_changed)
        self.lock_row.connect("notify::value", self.on_lock_changed)
        self.fps_row.connect("notify::value", self.on_fps_changed)
        self.blank_display_row.connect("notify::value", self.on_blank_display_changed)
        self.ampm_switch.connect("notify::active", self.on_ampm_toggled)
        self.clock_overlay_switch.connect("notify::active", self.on_clock_overlay_toggled)
        self.clock_overlay_position_row.connect("notify::selected", self.on_clock_overlay_position_changed)
        self.clock_overlay_opacity_row.connect("notify::value", self.on_clock_overlay_opacity_changed)
        self.search_entry.connect("search-changed", self.on_picker_filter_changed)
        self.category_row.connect("notify::selected", self.on_picker_filter_changed)
        self.favorites_only_switch.connect("notify::active", self.on_picker_filter_changed)
        self.favorite_button.connect("clicked", self.on_toggle_favorite)
        for (scene_name, option_name), row in self.scene_option_rows.items():
            row.connect(
                "notify::value",
                lambda changed_row, _pspec, scene=scene_name, option=option_name:
                    self.on_scene_option_changed(scene, option, changed_row.get_value()),
            )
        self.autostart_switch.connect("notify::active", self.on_autostart_toggled)

    def load_state(self):
        cfg = load_config()

        is_random = cfg.get("random", False) and self._preview_override is None
        self.random_switch.set_active(is_random)
        active = self._preview_override or cfg.get("active")
        self.selected_scene = active if active in self.screensaver_files else (
            self.screensaver_files[0] if self.screensaver_files else None
        )
        self._rebuild_screensaver_picker(self.selected_scene)
        self._build_monitor_assignment_rows(cfg)
        for (scene_name, option_name), row in self.scene_option_rows.items():
            row.set_value(
                config_store.get_scene_options(cfg, scene_name).get(
                    option_name, self.scene_option_specs[(scene_name, option_name)]["default"]
                )
            )
        self._update_customization_controls()

        self.idle_row.set_value(cfg.get("idle_seconds", 300))
        self.lock_row.set_value(cfg.get("lock_after_seconds", 300))
        self.fps_row.set_value(cfg.get("fps_limit", 30))
        self.blank_display_row.set_value(cfg.get("blank_display_after_minutes", 0))

        self.ampm_switch.set_active(cfg.get("clock_format", "24h") == "12h")
        self.clock_overlay_switch.set_active(cfg.get("clock_overlay", False))
        position = cfg.get("clock_overlay_position", "bottom-right")
        self.clock_overlay_position_row.set_selected(self.clock_overlay_positions.index(position) if position in self.clock_overlay_positions else 3)
        self.clock_overlay_opacity_row.set_value(cfg.get("clock_overlay_opacity", 80))
        self.matugen_path_entry.set_text(cfg.get("matugen_colors_path", DEFAULT_MATUGEN_COLORS_PATH))
        self.lock_message_entry.set_text(cfg.get("lock_message", ""))

        # Query systemd asynchronously so opening Settings never blocks GTK.
        self.autostart_switch.set_sensitive(False)

        def on_enabled_checked(success, stdout, stderr):
            enabled = stdout.strip() == "enabled"
            self._autostart_enabled = enabled
            self._autostart_updating = True
            self.autostart_switch.set_active(enabled)
            self._autostart_updating = False
            self.autostart_switch.set_sensitive(True)
            if not success and stdout.strip() not in ("disabled", "static", "masked", "not-found"):
                detail = stderr.strip() or "systemctl --user is-enabled failed"
                self.toast_overlay.add_toast(Adw.Toast.new(detail))

        self._autostart_enabled = False
        self._autostart_updating = False
        self._run_systemctl_async(["is-enabled", SERVICE_NAME], on_enabled_checked)

        def on_active_checked(success, stdout, _stderr):
            state = stdout.strip() if success else "unknown"
            if state == "active":
                subtitle = "Launch when idle (service running)"
            elif state in ("inactive", "failed", "deactivating"):
                subtitle = f"Launch when idle (service {state})"
            else:
                subtitle = "Launch when idle (service state unavailable)"
            self.autostart_row.set_subtitle(subtitle)

        self._run_systemctl_async(["is-active", SERVICE_NAME], on_active_checked)
        self.refresh_shortcut_label()

    def _build_monitor_assignment_rows(self, cfg):
        """Create selectors for monitors connected to this session."""
        display = Gdk.Display.get_default()
        monitors = []
        if display is not None:
            try:
                model = display.get_monitors()
                for index in range(model.get_n_items()):
                    monitor = model.get_item(index)
                    if monitor is None:
                        continue
                    key = config_store.monitor_identifier(monitor, index)
                    try:
                        connector = monitor.get_connector()
                    except Exception:
                        connector = None
                    try:
                        model_name = monitor.get_model()
                    except Exception:
                        model_name = None
                    label = connector or model_name or ("Display " + str(index + 1))
                    monitors.append((key, str(label)))
            except Exception as exc:
                print("Could not enumerate monitors for settings: " + str(exc), file=sys.stderr)
        if not monitors:
            self.monitor_assignment_group.add(Adw.ActionRow(
                title="No connected monitors detected",
                subtitle="Assignments appear when a display is available",
            ))
            return
        scenes = list(self.screensaver_files)
        options = ["Use global default"] + [display_name(scene) for scene in scenes]
        assignments = cfg.get("monitor_screensavers", {})
        for key, label in monitors:
            row = Adw.ComboRow(title=label, subtitle=key)
            row.set_model(Gtk.StringList.new(options))
            selected = assignments.get(key)
            row.set_selected(scenes.index(selected) + 1 if selected in scenes else 0)
            row.connect("notify::selected", self.on_monitor_assignment_changed, key)
            self.monitor_assignment_group.add(row)
            self.monitor_assignment_rows[key] = row

    def on_monitor_assignment_changed(self, row, _pspec, monitor_key):
        index = row.get_selected()
        cfg = load_config()
        assignments = dict(cfg.get("monitor_screensavers", {}))
        if index == 0:
            assignments.pop(monitor_key, None)
        elif 0 < index <= len(self.screensaver_files):
            assignments[monitor_key] = self.screensaver_files[index - 1]
        if self._save_config(monitor_screensavers=assignments):
            self.toast_overlay.add_toast(Adw.Toast.new("Monitor assignment saved"))

    def _rebuild_screensaver_picker(self, preserve_scene=None):
        cfg = load_config()
        category_index = self.category_row.get_selected()
        category = CATEGORY_OPTIONS[category_index] if category_index < len(CATEGORY_OPTIONS) else "All categories"
        filtered = filter_screensavers(
            self.screensaver_files,
            query=self.search_entry.get_text(),
            category=category,
            favorites=cfg.get("favorites", []),
            favorites_only=self.favorites_only_switch.get_active(),
        )
        self.filtered_screensaver_files = filtered
        self._picker_updating = True
        try:
            if filtered:
                self.combo_row.set_model(Gtk.StringList.new([display_name(f) for f in filtered]))
                selected = filtered.index(preserve_scene) if preserve_scene in filtered else Gtk.INVALID_LIST_POSITION
                self.combo_row.set_selected(selected)
                subtitle = "" if preserve_scene in filtered else "Current selection is hidden by filters; it has not changed"
            else:
                self.combo_row.set_model(Gtk.StringList.new(["No matching scenes"]))
                self.combo_row.set_selected(0)
                subtitle = "No scenes match these filters; current selection is unchanged"
            self.combo_row.set_subtitle(subtitle)
            self.combo_row.set_sensitive(bool(filtered) and not self.random_switch.get_active())
        finally:
            self._picker_updating = False
        self._refresh_favorite_button()

    def _update_customization_controls(self):
        self.customization_group.set_visible(
            self.selected_scene in config_store.SCENE_OPTION_SCHEMA
        )
        for (scene_name, _option_name), row in self.scene_option_rows.items():
            row.set_visible(scene_name == self.selected_scene)

    def on_scene_option_changed(self, scene_name, option_name, value):
        if self._picker_updating or scene_name != self.selected_scene:
            return
        cfg = load_config()
        all_options = dict(cfg.get("screensaver_options", {}))
        scene_options = dict(all_options.get(scene_name, {}))
        scene_options[option_name] = value
        all_options[scene_name] = scene_options
        if self._save_config(screensaver_options=all_options):
            self._update_preview()

    def on_picker_filter_changed(self, *_args):
        self._rebuild_screensaver_picker(self.selected_scene)

    def _refresh_favorite_button(self):
        favorites = load_config().get("favorites", [])
        is_favorite = self.selected_scene in favorites
        self.favorite_button.set_label("★ Remove from favorites" if is_favorite else "☆ Add to favorites")
        self.favorite_button.set_sensitive(self.selected_scene in self.screensaver_files)

    def on_toggle_favorite(self, _button):
        if self.selected_scene not in self.screensaver_files:
            return
        favorites = list(load_config().get("favorites", []))
        if self.selected_scene in favorites:
            favorites.remove(self.selected_scene)
        else:
            favorites.append(self.selected_scene)
        if self._save_config(favorites=favorites):
            self._rebuild_screensaver_picker(self.selected_scene)


    def on_preview_activity_changed(self, _win, _pspec):
        """Unload animated preview pages while Settings is not the active window."""
        if not HAS_WEBKIT or getattr(self, "preview_web", None) is None:
            return
        try:
            if self.get_property("is-active"):
                self._update_preview()
            else:
                self.preview_web.stop_loading()
                self.preview_web.load_uri("about:blank")
        except Exception as exc:
            print(f"Could not suspend inactive preview: {exc}", file=sys.stderr)

    def _update_preview(self):
        if not HAS_WEBKIT or not hasattr(self, "preview_web") or self.preview_web is None:
            return
        try:
            if not self.get_property("is-active"):
                return
        except Exception:
            pass
        cfg = load_config()
        sync_matugen_colors_link(cfg)
        if self._preview_override in self.screensaver_files:
            fn = self._preview_override
        elif cfg.get("random", False):
            # Random mode previews a random style each refresh.
            fn = self.screensaver_files[random.randrange(len(self.screensaver_files))] if self.screensaver_files else None
        else:
            fn = self.selected_scene
        if fn in self.screensaver_files:
            path = os.path.join(SCREENSAVER_DIR, fn)
            fmt = cfg.get("clock_format", "24h")
            params = {"format": fmt, "clockOverlay": "1" if cfg.get("clock_overlay", False) else "0", "clockOverlayPosition": cfg.get("clock_overlay_position", "bottom-right"), "clockOverlayOpacity": str(cfg.get("clock_overlay_opacity", 80))}
            params.update(config_store.get_scene_options(cfg, fn))
            uri = Gio.File.new_for_path(path).get_uri()
            uri = f"{uri}?{urlencode(params)}"
            try:
                self.preview_web.load_uri(uri)
            except Exception:
                pass

    def _save_config(self, **updates):
        try:
            save_config(**updates)
            return True
        except Exception as exc:
            print(f"Failed to save Material Screensaver settings: {exc}", file=sys.stderr)
            self.toast_overlay.add_toast(
                Adw.Toast.new(f"Settings could not be saved: {exc}")
            )
            return False

    def on_lock_message_apply(self, _button):
        message = self.lock_message_entry.get_text().strip()
        if len(message) > 160:
            self.toast_overlay.add_toast(Adw.Toast.new("Lock message must be 160 characters or fewer"))
            return
        if not self._save_config(lock_message=message):
            return
        self.toast_overlay.add_toast(Adw.Toast.new("Lock message saved; it appears on the next screensaver launch"))

    def on_lock_message_clear(self, _button):
        self.lock_message_entry.set_text("")
        if self._save_config(lock_message=""):
            self.toast_overlay.add_toast(Adw.Toast.new("Lock message cleared"))

    def on_matugen_path_apply(self, _button):
        path = os.path.expanduser(self.matugen_path_entry.get_text().strip())
        if not path:
            path = DEFAULT_MATUGEN_COLORS_PATH
        if not os.path.isabs(path):
            self.toast_overlay.add_toast(Adw.Toast.new("Enter an absolute file path"))
            return
        path = os.path.normpath(path)
        if not self._save_config(matugen_colors_path=path):
            return
        cfg = load_config()
        sync_matugen_colors_link(cfg)
        self._update_preview()
        self.toast_overlay.add_toast(Adw.Toast.new("Matugen colors path saved"))

    def refresh_shortcut_label(self):
        try:
            settings = get_keybinding_settings()
            binding = settings.get_string("binding") if settings is not None else ""
        except GLib.Error:
            binding = ""
        if binding:
            ok, keyval, mods = Gtk.accelerator_parse(binding)
            label = Gtk.accelerator_get_label(keyval, mods) if ok else binding
            self.shortcut_row.set_subtitle(label)
        else:
            self.shortcut_row.set_subtitle("Not set")
        self.clear_shortcut_button.set_sensitive(bool(binding))

    def on_clear_shortcut(self, _btn):
        settings = get_keybinding_settings()
        if settings is not None:
            settings.set_string("binding", "")
        self.refresh_shortcut_label()

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
            # Super+Q is reserved for dismissing the screensaver; binding the
            # toggle to the same chord would race with the close handler.
            if accel.lower() in ("<super>q", "<meta>q"):
                title.set_label("Super+Q is reserved for close")
                hint.set_label("Choose a different shortcut — Esc to cancel")
                return True
            get_keybinding_settings(create=True).set_string("binding", accel)
            self.refresh_shortcut_label()
            dialog.close()
            return True

        controller.connect("key-pressed", on_key)
        dialog.add_controller(controller)
        dialog.present()

    def on_random_toggled(self, switch, _pspec):
        self._preview_override = None
        is_random = switch.get_active()
        self._save_config(random=is_random)
        self.combo_row.set_sensitive(bool(self.filtered_screensaver_files) and not is_random)
        self._update_preview()

    def on_screensaver_changed(self, row, _pspec):
        if self._picker_updating:
            return
        idx = row.get_selected()
        if not 0 <= idx < len(self.filtered_screensaver_files):
            return
        had_preview_override = self._preview_override is not None
        self._preview_override = None
        self.selected_scene = self.filtered_screensaver_files[idx]
        updates = {"active": self.selected_scene}
        if had_preview_override:
            updates["random"] = False
        self._save_config(**updates)
        self._refresh_favorite_button()
        self._update_customization_controls()
        self._update_preview()

    def on_idle_changed(self, row, _pspec):
        self._save_config(idle_seconds=int(row.get_value()))

    def on_lock_changed(self, row, _pspec):
        self._save_config(lock_after_seconds=int(row.get_value()))

    def on_fps_changed(self, row, _pspec):
        if self._save_config(fps_limit=int(row.get_value())):
            self._update_preview()

    def on_blank_display_changed(self, row, _pspec):
        self._save_config(blank_display_after_minutes=int(row.get_value()))

    def on_ampm_toggled(self, switch, _pspec):
        self._save_config(clock_format="12h" if switch.get_active() else "24h")
        self._update_preview()

    def on_clock_overlay_toggled(self, switch, _pspec):
        if self._save_config(clock_overlay=switch.get_active()):
            self._update_preview()

    def on_clock_overlay_position_changed(self, row, _pspec):
        index = row.get_selected()
        if 0 <= index < len(self.clock_overlay_positions):
            if self._save_config(clock_overlay_position=self.clock_overlay_positions[index]):
                self._update_preview()

    def on_clock_overlay_opacity_changed(self, row, _pspec):
        if self._save_config(clock_overlay_opacity=int(row.get_value())):
            self._update_preview()

    def _run_systemctl_async(self, args, on_finished):
        """Run a user-systemd command off the GTK main loop."""
        try:
            flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            proc = Gio.Subprocess.new(["systemctl", "--user", *args], flags)
        except Exception as exc:
            on_finished(False, "", str(exc))
            return

        def completed(process, result):
            try:
                stdout, stderr = process.communicate_utf8_finish(result)
                on_finished(process.get_successful(), stdout or "", stderr or "")
            except Exception as exc:
                on_finished(False, "", str(exc))

        proc.communicate_utf8_async(None, None, completed)

    def on_autostart_toggled(self, switch, _pspec):
        if getattr(self, "_autostart_updating", False):
            return
        desired = switch.get_active()
        previous = getattr(self, "_autostart_enabled", not desired)
        action = "enable" if desired else "disable"
        switch.set_sensitive(False)

        def on_finished(success, _stdout, stderr):
            switch.set_sensitive(True)
            if success:
                self._autostart_enabled = desired
                self.autostart_row.set_subtitle(
                    "Launch when idle (service running)" if desired
                    else "Launch when idle (service inactive)"
                )
                return
            # Keep the UI honest when systemd rejects the change.
            self._autostart_updating = True
            switch.set_active(previous)
            self._autostart_updating = False
            detail = stderr.strip() or f"systemctl --user {action} failed"
            self.toast_overlay.add_toast(Adw.Toast.new(detail))

        self._run_systemctl_async([action, "--now", SERVICE_NAME], on_finished)


class ScreensaverApp(Adw.Application):
    def __init__(self, non_unique=False):
        flags = Gio.ApplicationFlags.NON_UNIQUE if non_unique else Gio.ApplicationFlags.FLAGS_NONE
        super().__init__(
            application_id="io.github.sakib.MaterialScreensaverSettings",
            flags=flags,
        )

    def do_activate(self):
        win = self.props.active_window or ScreensaverWindow(self)
        win.present()


def main(argv=None):
    global REQUESTED_PREVIEW
    REQUESTED_PREVIEW = None
    parser = argparse.ArgumentParser(
        description="Open Material Screensaver settings or a specific live scene preview."
    )
    parser.add_argument(
        "--settings", action="store_true",
        help="open settings (the default action)",
    )
    parser.add_argument(
        "--preview", metavar="SCENE.html",
        help="open settings with the named scene selected in the live preview",
    )
    parser.add_argument(
        "--list-screensavers", action="store_true",
        help="print available scene filenames and exit",
    )
    args = parser.parse_args(argv)
    scenes = list_screensavers()
    if args.list_screensavers:
        if args.preview:
            parser.error("--list-screensavers cannot be combined with --preview")
        if scenes:
            print("\n".join(scenes))
        return 0
    if args.preview:
        if os.path.basename(args.preview) != args.preview or args.preview not in scenes:
            print(f"Unknown screensaver scene: {args.preview}", file=sys.stderr)
            return 2
        if not HAS_WEBKIT:
            print("Live preview requires WebKitGTK 6.0", file=sys.stderr)
            return 2
        REQUESTED_PREVIEW = args.preview
    # A preview deep-link must open a fresh window even if Settings is already
    # running; otherwise the existing app instance would ignore this process's
    # requested scene. Ordinary Settings launches keep single-instance behavior.
    return ScreensaverApp(non_unique=bool(args.preview)).run([])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
