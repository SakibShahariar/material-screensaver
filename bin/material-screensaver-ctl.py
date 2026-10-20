#!/usr/bin/env python3
"""
Control script for the Material screensaver — WebKitGTK backend.

Usage:
  material-screensaver-ctl.py toggle   # show if hidden, hide if visible
  material-screensaver-ctl.py start    # show
  material-screensaver-ctl.py stop     # hide
  material-screensaver-ctl.py daemon   # run idle watcher (systemd service)

Settings (active screensaver, idle timeout, clock_format, random) are read
from ~/.config/material-screensaver/config.json (written by GUI).
Screensavers are file:// html in ~/.local/share/material-screensaver/screensavers.

Backend: single Gtk4 + WebKit 6.0 fullscreen window(s) (one per monitor),
SessionManager inhibit, input grab. No external browser, no PID file.
When daemon is running, start/stop/toggle delegate to daemon via D-Bus
(io.github.sakib.MaterialScreensaver); otherwise they run a standalone
viewer.
"""
import os
import sys
import json
import glob
import material_screensaver_config as config_store
import random
import subprocess
import atexit
import signal
import tempfile
from urllib.parse import urlencode

SCREENSAVER_DIR = os.path.expanduser("~/.local/share/material-screensaver/screensavers")
CONFIG_PATH = os.path.expanduser("~/.config/material-screensaver/config.json")
DEFAULT_MATUGEN_COLORS_PATH = config_store.DEFAULT_MATUGEN_COLORS_PATH
DEFAULT_CONFIG = config_store.DEFAULT_CONFIG

# D-Bus service for daemon delegation (PID file gone)
SERVICE_NAME = "io.github.sakib.MaterialScreensaver"
OBJECT_PATH = "/io/github/sakib/MaterialScreensaver"
INTERFACE_NAME = "io.github.sakib.MaterialScreensaver"

# Viewer state (daemon or standalone)
_viewer_windows = []  # list[Gtk.Window]
_viewer_inhibit_cookie = None
_viewer_inhibit_proxy = None
_daemon_app = None  # Gtk.Application for daemon (Wayland fullscreen needs ApplicationWindow)
_idle_proxy = None  # Gio.DBusProxy for org.gnome.Mutter.IdleMonitor (daemon only)
_idle_watch_ids = {"idle": None, "active": None}
_lock_timeout_id = None  # GLib source id for lock after screensaver
_session_locked = False  # suppress idle-triggered shows during a GNOME lock
_login1_session_proxy = None  # retain logind session proxy for lock notifications
_user_hook_processes = {}  # retain asynchronous Gio.Subprocess objects until exit
_saved_overlay_key = None  # saved org.gnome.mutter overlay-key while Super+Q is exclusive
_saved_shell_toggle = None  # saved shell toggle-overview
_is_showing = False  # guard double-Show TOCTOU
_pending_sources = []  # GLib source ids for fullscreen retry / gc to cancel on Hide
_viewer_process = None  # subprocess.Popen for isolated viewer (daemon only, keeps daemon 30M flat)
_viewer_child_watch_id = None  # GLib child-watch source; removed before synchronous Hide/reap
_ephemeral_ctx = None  # single ephemeral WebContext reused across Shows (fixes per-Show leak)
_is_viewer_mode = False  # True in viewer subprocess (isolated WebKit, daemon stays lean)
_viewer_loop = None  # GLib.MainLoop for viewer subprocess

_valid_int = config_store._valid_int
normalize_config = config_store.normalize_config


def load_config():
    return config_store.load_config(CONFIG_PATH)


def update_lock_message(message):
    """Persist a short, plain-text viewer message; empty text clears it."""
    if not isinstance(message, str):
        raise ValueError("lock message must be text")
    message = "".join(char for char in message.strip() if char.isprintable())[:160]
    config_store.save_config(CONFIG_PATH, lock_message=message)
    return message


def list_screensavers():
    """Return {filename: full_path} for every .html screensaver."""
    return {
        os.path.basename(path): path
        for path in config_store.list_screensavers(SCREENSAVER_DIR)
    }

def sync_matugen_colors_link(cfg=None):
    if not isinstance(cfg, dict):
        cfg = load_config()
    return config_store.sync_matugen_colors_link(SCREENSAVER_DIR, cfg)

def get_active_html_path(cfg):
    sync_matugen_colors_link(cfg)
    screensavers = list_screensavers()
    if not screensavers:
        print(f"No screensaver .html files found in {SCREENSAVER_DIR}", file=sys.stderr)
        return None
    if cfg.get("random", False):
        return random.choice(list(screensavers.values()))
    active = cfg.get("active")
    if active and active in screensavers:
        return screensavers[active]
    return next(iter(screensavers.values()))  # alphabetically first

def has_graphical_session():
    """Avoid initializing GTK/WebKit when no display connection is possible."""
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))

# ---------- SessionManager inhibit ----------
def _get_session_proxy():
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            "org.gnome.SessionManager", "/org/gnome/SessionManager",
            "org.gnome.SessionManager", None)
        return proxy
    except Exception:
        return None

def _dbg(msg):
    """Best-effort debug log, active only when MS_DEBUG is set (keeps idle silent)."""
    if os.environ.get("MS_DEBUG"):
        try:
            print(f"[material-screensaver] {msg}", file=sys.stderr, flush=True)
        except Exception:
            pass

def _inhibit():
    global _viewer_inhibit_cookie, _viewer_inhibit_proxy
    if _viewer_inhibit_cookie is not None:
        return
    proxy = _get_session_proxy()
    if proxy is None:
        _dbg("inhibit: no session proxy (SessionManager unavailable)")
        return
    try:
        from gi.repository import GLib
        # flags 8 = inhibit idle, reason visible in gnome logs
        res = proxy.call_sync("Inhibit",
            GLib.Variant("(susu)", ("material-screensaver", 0, "Screensaver active", 8)),
            0, -1, None)
        _viewer_inhibit_cookie = res.unpack()[0]
        _viewer_inhibit_proxy = proxy
    except Exception as e:
        _dbg(f"inhibit failed: {e}")

def _uninhibit():
    global _viewer_inhibit_cookie, _viewer_inhibit_proxy
    if _viewer_inhibit_cookie is None or _viewer_inhibit_proxy is None:
        return
    try:
        from gi.repository import GLib
        _viewer_inhibit_proxy.call_sync("Uninhibit",
            GLib.Variant("(u)", (_viewer_inhibit_cookie,)), 0, -1, None)
    except Exception as e:
        _dbg(f"uninhibit failed: {e}")
    _viewer_inhibit_cookie = None
    _viewer_inhibit_proxy = None

# ---------- WebKit viewer ----------
# Shared WebKit context to avoid spawning a new NetworkProcess per Show
_shared_web_context = None

def _get_shared_context():
    global _shared_web_context
    if _shared_web_context is not None:
        return _shared_web_context
    try:
        import gi
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit
        # Use default context (shared NetworkProcess) — prevents bwrap/WebKitNetworkProcess leak per Show
        _shared_web_context = WebKit.WebContext.get_default()
        # Reduce cache to avoid memory bloat across shows
        try:
            _shared_web_context.set_cache_model(WebKit.CacheModel.DOCUMENT_VIEWER)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _get_shared_context: {exc}")
    except Exception:
        _shared_web_context = None
    return _shared_web_context

def _kill_orphan_webkit():
    """Terminate lingering WebKit descendants without blocking the GLib loop.

    Linux /proc avoids spawning synchronous `ps` subprocesses. Matching
    processes receive SIGTERM first; a GLib timeout sends SIGKILL only if the
    same PID still has a matching command line, avoiding a blind delayed kill
    if the PID has already been reused.
    """
    import os
    import signal

    def _read_process(pid):
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as stream:
                stat = stream.read()
            # comm is parenthesized and may itself contain spaces or ')'.
            tail = stat[stat.rfind(")") + 2:].split()
            if len(tail) < 2:
                return None
            ppid = int(tail[1])
            with open(f"/proc/{pid}/cmdline", "rb") as stream:
                raw_cmd = stream.read()
            cmd = raw_cmd.replace(b"\0", b" ").decode(errors="replace").strip()
            return ppid, cmd
        except (OSError, ValueError, IndexError):
            return None

    try:
        process_entries = os.listdir("/proc")
    except OSError:
        return 0

    process_info = {}
    for entry in process_entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        info = _read_process(pid)
        if info is not None:
            process_info[pid] = info

    # Walk all descendants, not just children and grandchildren: WebKit's
    # sandbox helpers can add another process layer on some distributions.
    children = {}
    for pid, (ppid, _cmd) in process_info.items():
        children.setdefault(ppid, []).append(pid)
    descendants = []
    pending = list(children.get(os.getpid(), ()))
    seen = set()
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        descendants.append(pid)
        pending.extend(children.get(pid, ()))

    def _is_webkit_helper(cmd):
        return ("WebKitNetworkProcess" in cmd
                or "WebKitWebProcess" in cmd
                or ("bwrap" in cmd and "xdg-dbus-proxy" in cmd)
                or "WebKitGTK" in cmd)

    to_reap = []
    for pid in descendants:
        cmd = process_info[pid][1]
        if not _is_webkit_helper(cmd):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            to_reap.append((pid, cmd))
        except (ProcessLookupError, PermissionError, OSError):
            continue

    if to_reap:
        try:
            import gi
            gi.require_version("GLib", "2.0")
            from gi.repository import GLib

            def _force_kill():
                for pid, original_cmd in to_reap:
                    current = _read_process(pid)
                    if current is None or not _is_webkit_helper(current[1]):
                        continue
                    # Require a matching process identity, not just a reused PID.
                    if current[1] != original_cmd:
                        continue
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(150, _force_kill)
        except Exception:
            # If GLib is unavailable, leave SIGTERM to complete naturally rather
            # than block this caller with sleep() or immediately escalate.
            pass

    return len(to_reap)

def _create_viewer_windows(html_path, clock_format="24h", scene_options=None):
    """Create one fullscreen Gtk.Window per monitor with WebKit WebView."""
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Gtk, Gdk, Gio, WebKit, GLib

    # Clean lingering WebKit descendants before creating new windows. The
    # cleanup uses /proc and schedules escalation, so it does not block GTK.
    try:
        _kill_orphan_webkit()
        if is_viewer_active():
            hide_viewer()
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")

    display = Gdk.Display.get_default()
    if display is None:
        try:
            Gtk.init()
            display = Gdk.Display.get_default()
        except Exception:
            display = None

    monitors = []
    if display is not None:
        try:
            lm = display.get_monitors()
            n = lm.get_n_items()
            for i in range(n):
                try:
                    m = lm.get_item(i)
                    if m is not None:
                        monitors.append(m)
                except Exception:
                    continue
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")
    if not monitors:
        monitors = [None]

    # Build a real file URI so user-added names containing spaces, #, ?, or
    # non-ASCII characters are not misinterpreted as URL syntax.
    uri = Gio.File.new_for_path(html_path).get_uri()
    params = {"format": clock_format}
    if isinstance(scene_options, dict):
        params.update(scene_options)
    uri = f"{uri}?{urlencode(params)}"
    windows = []
    global _ephemeral_ctx
    if _ephemeral_ctx is None:
        try:
            _ephemeral_ctx = WebKit.WebContext.new_ephemeral()
            try:
                _ephemeral_ctx.set_cache_model(WebKit.CacheModel.DOCUMENT_VIEWER)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")
        except Exception:
            _ephemeral_ctx = _get_shared_context()
    ctx = _ephemeral_ctx
    for mon in monitors:
        try:
            if _daemon_app is not None:
                win = Gtk.ApplicationWindow(application=_daemon_app, title="Material Screensaver")
            else:
                win = Gtk.Window(title="Material Screensaver")
        except Exception:
            win = Gtk.Window(title="Material Screensaver")
        win.set_decorated(False)
        try:
            win.set_modal(True)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")
        # Set size to monitor geometry early (helps Wayland compositor place correctly)
        try:
            if mon is not None:
                geom = mon.get_geometry()
                win.set_default_size(geom.width, geom.height)
            else:
                win.set_default_size(1920, 1080)
        except Exception:
            win.set_default_size(1920, 1080)
        try:
            win.add_css_class("screensaver-window")
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")

        # Create WebView with shared context
        try:
            if ctx is not None:
                web = WebKit.WebView.new_with_context(ctx)
            else:
                web = WebKit.WebView()
        except Exception:
            web = WebKit.WebView()
        settings = web.get_settings()
        try:
            # Keep file:// pages under the normal same-origin policy. Relative
            # scripts/styles (including the Matugen stylesheet symlink) should
            # still load, but scene JavaScript must not read unrelated local files.
            settings.set_allow_file_access_from_file_urls(False)
            settings.set_allow_universal_access_from_file_urls(False)
            settings.set_enable_write_console_messages_to_stdout(False)
            settings.set_enable_javascript(True)
            # Prevent WebKit throttling when window is not focused (ghost 0.1% vs 87% fix)
            try:
                settings.set_enable_back_forward_navigation_gestures(False)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")
        # Optional shared clock/date overlay. Avoid duplicating clocks already in a scene.
        try:
            cfg = load_config()
            if cfg.get("clock_overlay", False):
                overlay_config = json.dumps({
                    "position": cfg.get("clock_overlay_position", "bottom-right"),
                    "opacity": cfg.get("clock_overlay_opacity", 80) / 100,
                    "format": cfg.get("clock_format", "24h"),
                })
                script = """(() => {
const config = __CLOCK_OVERLAY_CONFIG__;
const add = () => {
  if (!document.body || document.getElementById('material-screensaver-clock-overlay')) return;
  const clockLike = document.querySelector('time, [id*="clock" i], [class*="clock" i], [id*="date" i], [class*="date" i], [aria-label*="time" i], [aria-label*="date" i]');
  if (clockLike) return;
  const node = document.createElement('div');
  node.id = 'material-screensaver-clock-overlay';
  const time = document.createElement('div');
  const date = document.createElement('div');
  time.style.cssText = 'font-size:clamp(28px,4vw,64px);font-weight:600;line-height:1.1;letter-spacing:.02em';
  date.style.cssText = 'font-size:clamp(12px,1.25vw,20px);margin-top:8px;opacity:.9';
  node.append(time, date);
  const vertical = config.position.startsWith('top') ? 'top:3vh;' : 'bottom:3vh;';
  const horizontal = config.position.endsWith('left') ? 'left:3vw;' : 'right:3vw;';
  node.style.cssText = 'position:fixed;' + vertical + horizontal + 'z-index:2147483646;max-width:40vw;padding:16px 22px;border-radius:16px;background:rgba(20,20,24,' + config.opacity + ');color:#fff;font-family:system-ui,sans-serif;text-align:left;line-height:1.35;pointer-events:none;user-select:none;box-shadow:0 2px 18px rgba(0,0,0,.25)';
  document.body.appendChild(node);
  const tick = () => {
    const now = new Date();
    time.textContent = now.toLocaleTimeString([], config.format === '12h' ? {hour:'numeric',minute:'2-digit'} : {hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
    date.textContent = now.toLocaleDateString([], {weekday:'long',month:'long',day:'numeric'});
  };
  tick(); window.setInterval(tick, 1000);
};
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add, {once:true}); else add();
})();""".replace("__CLOCK_OVERLAY_CONFIG__", overlay_config)
                ucm = web.get_user_content_manager()
                overlay_script = WebKit.UserScript.new(
                    script,
                    WebKit.UserContentInjectedFrames.TOP_FRAME,
                    WebKit.UserScriptInjectionTime.END,
                    None,
                    None,
                )
                ucm.add_script(overlay_script)
        except Exception as exc:
            _dbg(f"Could not install clock overlay: {exc}")

        # Optional plain-text message overlay. JSON serialization and textContent
        # prevent the configured message from becoming executable HTML or JS.
        try:
            message = load_config().get("lock_message", "")
            if message:
                script = (
                    "(() => { const add = () => { if (!document.body || "
                    "document.getElementById('material-screensaver-lock-message')) return; "
                    "const node = document.createElement('div'); "
                    "node.id = 'material-screensaver-lock-message'; "
                    "node.textContent = " + json.dumps(message) + "; "
                    "node.setAttribute('role', 'note'); "
                    "node.style.cssText = 'position:fixed;left:3vw;bottom:3vh;z-index:2147483647;"
                    "max-width:70vw;padding:10px 16px;border-radius:12px;"
                    "background:rgba(20,20,24,.72);color:#fff;font:500 18px sans-serif;"
                    "line-height:1.35;pointer-events:none;white-space:pre-wrap;"
                    "overflow-wrap:anywhere;box-shadow:0 2px 14px rgba(0,0,0,.25)'; "
                    "document.body.appendChild(node); }; "
                    "if (document.readyState === 'loading') "
                    "document.addEventListener('DOMContentLoaded', add, {once:true}); "
                    "else add(); })();"
                )
                ucm = web.get_user_content_manager()
                message_script = WebKit.UserScript.new(
                    script,
                    WebKit.UserContentInjectedFrames.TOP_FRAME,
                    WebKit.UserScriptInjectionTime.END,
                    None,
                    None,
                )
                ucm.add_script(message_script)
        except Exception as exc:
            _dbg(f"Could not install lock message overlay: {exc}")

        # Hide cursor inside web content from the first paint — WebKit's CSS cursor
        # overrides the widget's Gdk cursor, so Gdk blank alone still shows default
        # arrow over the page until first motion. Inject a blanket cursor:none
        # except for interactive screensavers (solar-system manages its own cursor).
        is_interactive = "solar-system" in os.path.basename(html_path)
        if not is_interactive:
            try:
                ucm = web.get_user_content_manager()
                sheet = WebKit.UserStyleSheet.new(
                    "* { cursor: none !important; } html, body { cursor: none !important; }",
                    WebKit.UserContentInjectedFrames.ALL_FRAMES,
                    WebKit.UserStyleLevel.AUTHOR,
                    None, None)
                ucm.add_style_sheet(sheet)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")
        web.load_uri(uri)
        win.set_child(web)

        def on_key(ctrl, keyval, keycode, state, _win=win):
            # Only Super+Q closes, Super alone is consumed (no overview, no close)
            try:
                from gi.repository import Gdk
                is_q = keyval in (Gdk.KEY_q, Gdk.KEY_Q)
                has_super = bool(state & Gdk.ModifierType.SUPER_MASK)
                is_super = keyval in (Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, 65515, 65516)
                if is_q and has_super:
                    hide_viewer()
                    return True
                if is_super:
                    return True
                # Everything else falls through to the page (never closes).
                return False
            except Exception:
                try:
                    from gi.repository import Gtk
                    if Gtk.accelerator_valid(keyval, state):
                        name = Gtk.accelerator_name(keyval, state)
                        if name == "<Super>q":
                            hide_viewer()
                            return True
                        if name in ("Super_L", "Super_R", "<Super>Super_L", "<Super>Super_R"):
                            return True
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in on_key: {exc}")
                return False
        def on_click(ctrl, n_press, x, y, _win=win, _web=web):
            # Clicks never dismiss — only Super+Q does. Do not consume, so
            # interactive styles (solar-system) still receive them.
            return False
        def on_motion(ctrl, x, y, _win=win, _web=web):
            # Mouse movement never dismisses. Non-interactive styles keep the
            # cursor hidden; interactive styles manage their own pointer.
            return False
        # cursor helpers — permanently hidden for non-interactive styles
        # (solar-system is interactive and manages cursor via body.show-cursor CSS)
        try:
            gi.require_version("GdkPixbuf", "2.0")
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")
        def _hide_cursor(w, web=None):
            # for interactive (solar-system) let page manage cursor itself
            if is_interactive:
                return
            for tgt in ([w] + ([web] if web is not None else [])):
                try:
                    try:
                        from gi.repository import GdkPixbuf
                        pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1, 1)
                        pix.fill(0x00000000)
                        tex = Gdk.Texture.new_for_pixbuf(pix)
                        c = Gdk.Cursor.new_from_texture(tex, 0, 0, None)
                        tgt.set_cursor(c)
                        continue
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _hide_cursor: {exc}")
                    for name in ("none", "blank", "hidden", "invisible"):
                        try:
                            c = Gdk.Cursor.new_from_name(name, None)
                            if c is not None:
                                tgt.set_cursor(c)
                                break
                        except Exception:
                            continue
                    else:
                        tgt.set_cursor(Gdk.Cursor.new_from_name("none", None))
                except Exception:
                    try:
                        tgt.set_cursor(None)
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _hide_cursor: {exc}")
            # also hide web-content cursor via JS (WebKit CSS overrides widget cursor)
            if web is not None:
                try:
                    web.evaluate_javascript("document.documentElement.style.cursor='none';document.body&& (document.body.style.cursor='none')", -1, None, None, None, None, None)
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in _hide_cursor: {exc}")
        # robust initial hide — Wayland resets cursor on map/fullscreen, so schedule after realize/map/timeouts
        def _hide_now():
            try:
                _hide_cursor(win, web)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _hide_now: {exc}")
            return False
        def _schedule_hide():
            try:
                _hide_now()
                # also hide after realize/map and short delays to beat compositor resets
                def _deferred_hide():
                    _hide_now()
                    return False
                try:
                    GLib.idle_add(_deferred_hide, priority=GLib.PRIORITY_HIGH_IDLE)
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in _schedule_hide: {exc}")
                for ms in (50, 200, 600, 1200):
                    try:
                        GLib.timeout_add(ms, _deferred_hide)
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _deferred_hide: {exc}")
                # on realize/map — most reliable for Wayland
                for sig in ("realize", "map"):
                    try:
                        win.connect(sig, lambda *_: _hide_now())
                        web.connect(sig, lambda *_: _hide_now())
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _deferred_hide: {exc}")
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _schedule_hide: {exc}")
        try:
            _schedule_hide()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")
        try:
            key_ctrl = Gtk.EventControllerKey()
            key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            key_ctrl.connect("key-pressed", on_key)
            # also consume release of Super (Mutter triggers overview on release)
            def on_key_release(ctrl, keyval, keycode, state, _win=win):
                try:
                    from gi.repository import Gdk
                    is_super = keyval in (Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, 65515, 65516)
                    if is_super:
                        return True
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in on_key_release: {exc}")
                return False
            key_ctrl.connect("key-released", on_key_release)
            win.add_controller(key_ctrl)
            click = Gtk.GestureClick()
            click.connect("pressed", on_click)
            win.add_controller(click)
            motion = Gtk.EventControllerMotion()
            motion.connect("motion", on_motion)
            win.add_controller(motion)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")

        try:
            win.set_hide_on_close(False)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")

        # Wayland: present must happen after app is active and surface realized.
        # Using `present()` then `fullscreen()` immediately can create ghost (dash visible, WebProcess 0.1% throttled).
        # Fix: present now, fullscreen on idle after surface mapped. Also connect to map for fallback.
        def _do_fullscreen(w=win, d=display, wb=web):
            try:
                w.fullscreen()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
            try:
                w.set_visible(True)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
            try:
                w.grab_focus()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
            try:
                w.set_focus_visible(True)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
            try:
                _hide_cursor(w, wb)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
            try:
                w._show_time = GLib.get_monotonic_time()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
            # Seat grab after fullscreen (Wayland may fail — best effort)
            try:
                seat = d.get_default_seat() if d else None
                surf = w.get_surface()
                if seat and surf:
                    seat.grab(surf, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
            # ensure cursor hidden after launch (even if compositor reset it) — retry via timeouts
            try:
                _hide_cursor(w, wb)
                # schedule a couple more hides to survive Wayland cursor resets after fullscreen
                GLib.timeout_add(100, lambda: (_hide_cursor(w, wb), False)[1])
                GLib.timeout_add(500, lambda: (_hide_cursor(w, wb), False)[1])
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
            return False

        # Present immediately (required to create surface)
        try:
            win.present()
        except Exception:
            try:
                win.set_visible(True)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
        # Defer fullscreen to next idle so Wayland compositor has surface
        try:
            sid = GLib.idle_add(_do_fullscreen, priority=GLib.PRIORITY_HIGH_IDLE)
            try:
                _pending_sources.append(sid)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
            def _retry_fs(w=win):
                try:
                    if w.get_visible():
                        w.fullscreen()
                        w.present()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in _retry_fs: {exc}")
                return False
            sid2 = GLib.timeout_add(200, _retry_fs)
            sid3 = GLib.timeout_add(600, _retry_fs)
            try:
                _pending_sources.extend([sid2, sid3])
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
        except Exception:
            try:
                _do_fullscreen()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _do_fullscreen: {exc}")
        # Also ensure fullscreen + cursor hidden on map (covers case where idle fired before map)
        try:
            def _on_map(w, _pspec=None):
                try:
                    w.fullscreen()
                    w.present()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in _on_map: {exc}")
                try:
                    _hide_cursor(w, web)
                    GLib.timeout_add(100, lambda: (_hide_cursor(w, web), False)[1])
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in _on_map: {exc}")
                return False
            win.connect("map", _on_map)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")

        # keep ephemeral ctx ref on window to prevent early GC
        try:
            win._ephemeral_ctx = _ephemeral_ctx
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _create_viewer_windows: {exc}")
        windows.append(win)

    return windows

def is_viewer_active():
    """Local check (no D-Bus). True if we have visible viewer windows in this process or subprocess."""
    global _viewer_windows, _viewer_process
    # If daemon says not showing, treat as not active even if toplevel ghost lingers briefly after hide
    if not _is_showing:
        return False
    # Isolated viewer subprocess alive?
    if _viewer_process is not None:
        try:
            if _viewer_process.poll() is None:
                return True
            else:
                # clean stale reference
                _viewer_process = None
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in is_viewer_active: {exc}")
    for w in list(_viewer_windows):
        try:
            if w.get_visible():
                return True
        except Exception as e:
            continue
    # Fallback: scan toplevels for ghosts (created but not in _viewer_windows)
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        for tl in Gtk.Window.list_toplevels():
            try:
                if tl.get_title() == "Material Screensaver" and tl.get_visible():
                    return True
            except Exception as e:
                continue
    except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in is_viewer_active: {exc}")
    # Last resort: if any WebKit bwrap child still alive while we think hidden,
    # treat as active ghost (prevents Show from spawning duplicate that stays throttled)
    # We don't check here to avoid false positives during normal hide, but hide_viewer will clean anyway
    return False

# Locks the session once the screensaver has been visible for lock_after_seconds.
# Ordered by preference; each candidate must report success (rc==0) or the next
# one is tried. A failing call (rc!=0, e.g. org.gnome.ScreenSaver absent on
# modern GNOME) falls through instead of silently stopping the chain.
LOCK_COMMANDS = [
    ["gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
     "--object-path", "/org/gnome/ScreenSaver",
     "--method", "org.gnome.ScreenSaver.Lock"],
    ["loginctl", "lock-session"],
    ["xdg-screensaver", "lock"],
]

def _lock_screen():
    """Try supported session-lock commands; return True only when one succeeds."""
    for cmd in LOCK_COMMANDS:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=3)
        except Exception as exc:
            print(f"Session lock command failed ({cmd[0]}): {exc}", file=sys.stderr)
            continue  # binary missing or timed out -> try the next candidate
        if r.returncode == 0:
            return True
        detail = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        print(
            f"Session lock command failed ({cmd[0]}, exit {r.returncode}){suffix}",
            file=sys.stderr,
        )
    print("Unable to lock the session: all lock commands failed; keeping screensaver visible.", file=sys.stderr)
    return False

def _lock_screen_async(on_complete):
    """Try lock commands without blocking GLib's main loop.

    The callback receives True only after a command exits successfully. Failed
    candidates fall through in order, just like _lock_screen().
    """
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except Exception as exc:
        print(f"Cannot use asynchronous session locking: {exc}", file=sys.stderr)
        on_complete(False)
        return

    candidates = iter(LOCK_COMMANDS)

    def try_next():
        try:
            cmd = next(candidates)
        except StopIteration:
            print("Unable to lock the session: all lock commands failed; keeping screensaver visible.",
                  file=sys.stderr)
            on_complete(False)
            return
        try:
            proc = Gio.Subprocess.new(
                cmd, Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        except Exception as exc:
            print(f"Session lock command failed ({cmd[0]}): {exc}", file=sys.stderr)
            try_next()
            return

        def on_wait(proc, result, _user_data=None):
            try:
                succeeded = proc.wait_check_finish(result)
            except Exception as exc:
                print(f"Session lock command failed ({cmd[0]}): {exc}", file=sys.stderr)
                try_next()
                return
            if succeeded:
                on_complete(True)
            else:
                try_next()

        proc.wait_check_async(None, on_wait, None)


def _idle_watch_needs_refresh(
    current_idle_seconds, last_idle_seconds, watch_id,
    viewer_active=False, session_locked=False,
):
    """Refresh a stale/missing idle watch only while the desktop can activate it."""
    if viewer_active or session_locked:
        return False
    return current_idle_seconds != last_idle_seconds or watch_id is None


def _handle_viewer_exit(returncode):
    """Fail closed if the viewer crashes while a lock timeout is configured."""
    if returncode == 0:
        return
    try:
        lock_after = int(load_config().get("lock_after_seconds", 0) or 0)
    except (TypeError, ValueError):
        lock_after = 0
    if lock_after <= 0:
        return
    print(
        f"Viewer exited abnormally (status {returncode}); attempting immediate session lock.",
        file=sys.stderr,
    )
    def on_locked(locked):
        if not locked:
            print("Unable to lock the session after abnormal viewer exit.",
                  file=sys.stderr)
    _lock_screen_async(on_locked)


def _run_user_hook(event):
    """Run a configured lock/unlock argv asynchronously; never block the session."""
    if event not in ("lock", "unlock"):
        return
    command = load_config().get(f"{event}_hook", [])
    if not command:
        return
    process = None
    try:
        from gi.repository import Gio
        process = Gio.Subprocess.new(command, Gio.SubprocessFlags.NONE)
        process_key = id(process)
        _user_hook_processes[process_key] = process

        def completed(proc, result):
            try:
                proc.wait_check_finish(result)
            except Exception as exc:
                print(f"Configured {event} hook failed: {exc}", file=sys.stderr)
            finally:
                _user_hook_processes.pop(process_key, None)

        process.wait_check_async(None, completed)
    except Exception as exc:
        if process is not None:
            _user_hook_processes.pop(id(process), None)
        print(f"Could not start configured {event} hook: {exc}", file=sys.stderr)


def _on_screen_saver_active_changed(active):
    """Track GNOME lock state and keep idle callbacks from reopening the viewer."""
    global _session_locked
    was_locked = _session_locked
    _session_locked = bool(active)
    if was_locked != _session_locked:
        _run_user_hook("lock" if _session_locked else "unlock")
    if _session_locked:
        _dbg("session lock detected; hiding viewer and suspending idle watch")
        if is_viewer_active() or _is_showing:
            try:
                hide_viewer()
            except Exception as exc:
                print(f"Failed to hide viewer on session lock: {exc}", file=sys.stderr)
        return
    _dbg("session unlocked; re-arming idle watch")
    try:
        _daemon_switch_to_idle_watch()
    except Exception as exc:
        print(f"Failed to re-arm idle watch after unlock: {exc}", file=sys.stderr)

def _monitor_login1_session_lock():
    """Use logind LockedHint as a fallback to GNOME's optional ScreenSaver signal."""
    global _login1_session_proxy, _session_locked
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        manager = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            "org.freedesktop.login1", "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager", None,
        )
        session_id = os.environ.get("XDG_SESSION_ID")
        if session_id:
            result = manager.call_sync(
                "GetSession", GLib.Variant("(s)", (session_id,)),
                Gio.DBusCallFlags.NONE, 2000, None,
            )
        else:
            result = manager.call_sync(
                "GetSessionByPID", GLib.Variant("(u)", (os.getpid(),)),
                Gio.DBusCallFlags.NONE, 2000, None,
            )
        (session_path,) = result.unpack()
        proxy = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            "org.freedesktop.login1", session_path,
            "org.freedesktop.login1.Session", None,
        )
        _login1_session_proxy = proxy

        def on_properties_changed(_proxy, changed, _invalidated):
            value = changed.lookup_value("LockedHint", None)
            if value is not None:
                try:
                    _on_screen_saver_active_changed(value.get_boolean())
                except Exception as exc:
                    print(f"Failed to process logind lock state: {exc}", file=sys.stderr)

        proxy.connect("g-properties-changed", on_properties_changed)
        locked = proxy.get_cached_property("LockedHint")
        if locked is not None:
            # This is an initial snapshot, not a transition; do not run hooks
            # merely because the daemon started while the session was locked.
            _session_locked = locked.get_boolean()
            if not _session_locked:
                try:
                    _daemon_switch_to_idle_watch()
                except Exception as exc:
                    print(f"Failed to arm idle watch from initial logind state: {exc}", file=sys.stderr)
        _dbg("subscribed to systemd-logind LockedHint")
        return True
    except Exception as exc:
        print(f"Unable to monitor session lock state via systemd-logind: {exc}", file=sys.stderr)
        return False


def _schedule_lock():
    global _lock_timeout_id
    try:
        if _lock_timeout_id is not None:
            try:
                from gi.repository import GLib
                GLib.source_remove(_lock_timeout_id)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _schedule_lock: {exc}")
            _lock_timeout_id=None
        cfg=load_config()
        secs=int(cfg.get("lock_after_seconds", 300) or 0)
        if secs <=0:
            return
        # Don't gate on is_viewer_active here — windows are only present()'d and fullscreen deferred to idle,
        # so get_visible may still be false and lock would never schedule on first Show
        from gi.repository import GLib
        def _do_lock():
            global _lock_timeout_id
            _lock_timeout_id=None
            if is_viewer_active():
                # Never dismiss the screensaver unless a lock command reports success.
                # Async execution keeps the GTK/GLib main loop responsive.
                def on_locked(locked):
                    if locked:
                        try:
                            hide_viewer()
                        except Exception as exc:
                            print(f"Failed to hide viewer after session lock: {exc}",
                                  file=sys.stderr)
                _lock_screen_async(on_locked)
            return False
        _lock_timeout_id = GLib.timeout_add_seconds(secs, _do_lock)
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in _schedule_lock: {exc}")

def _cancel_lock():
    global _lock_timeout_id
    try:
        if _lock_timeout_id is not None:
            from gi.repository import GLib
            try:
                GLib.source_remove(_lock_timeout_id)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _cancel_lock: {exc}")
            _lock_timeout_id=None
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in _cancel_lock: {exc}")

def _inhibit_overview():
    global _saved_overlay_key, _saved_shell_toggle
    try:
        if _saved_overlay_key is not None:
            # already inhibited — re-assert that overlay-key stays '' (external reset guard)
            try:
                from gi.repository import Gio as _GioI2b
                _sb = _GioI2b.Settings.new("org.gnome.mutter")
                if _sb.get_string("overlay-key") != "":
                    _sb.set_string("overlay-key", "")
                    _GioI2b.Settings.sync()
                    subprocess.run(["gsettings", "set", "org.gnome.mutter", "overlay-key", "''"],
                                   capture_output=True, timeout=2)
                    subprocess.run(["dconf", "write", "/org/gnome/mutter/overlay-key", "''"],
                                   capture_output=True, timeout=2)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _inhibit_overview: {exc}")
            return
        # mutter overlay-key — main Super→overview
        out = subprocess.run(["gsettings", "get", "org.gnome.mutter", "overlay-key"],
                             capture_output=True, text=True, timeout=2)
        if out.returncode==0:
            cur = out.stdout.strip()
            _saved_overlay_key = cur
            # Gio.Settings sync for immediate Wayland effect (primary, most reliable)
            gio_ok = False
            gio_err = ""
            try:
                from gi.repository import Gio as _GioI2
                _s = _GioI2.Settings.new("org.gnome.mutter")
                before = _s.get_string("overlay-key")
                _s.set_string("overlay-key", "")
                _GioI2.Settings.sync()
                after = _s.get_string("overlay-key")
                gio_ok = (after == "")
                if not gio_ok:
                    gio_err = f"Gio after={after!r} before={before!r}"
            except Exception as e:
                gio_err = f"Gio exception {e}"
                pass
            set_rc = None
            dconf_rc = None
            if cur != "''":
                r1 = subprocess.run(["gsettings", "set", "org.gnome.mutter", "overlay-key", "''"],
                               capture_output=True, text=True, timeout=2)
                set_rc = r1.returncode
                r2 = subprocess.run(["dconf", "write", "/org/gnome/mutter/overlay-key", "''"],
                               capture_output=True, text=True, timeout=2)
                dconf_rc = r2.returncode
            # verify via both Gio and gsettings
            verify = ""
            try:
                chk = subprocess.run(["gsettings", "get", "org.gnome.mutter", "overlay-key"],
                                     capture_output=True, text=True, timeout=2)
                verify = chk.stdout.strip() if chk.returncode==0 else f"chk_rc={chk.returncode} err={chk.stderr.strip()}"
                if chk.returncode==0 and chk.stdout.strip() != "''":
                    subprocess.run(["dconf", "write", "/org/gnome/mutter/overlay-key", "''"],
                                   capture_output=True, timeout=2)
                    # re-read
                    chk2 = subprocess.run(["gsettings", "get", "org.gnome.mutter", "overlay-key"],
                                         capture_output=True, text=True, timeout=2)
                    verify += f" -> retry {chk2.stdout.strip()}"
            except Exception as e:
                verify = f"verify_exc {e}"
            try:
                print(f"[overview] inhibit Gio ok={gio_ok} err={gio_err} set_rc={set_rc} dconf_rc={dconf_rc} verify={verify}", file=sys.stderr)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _inhibit_overview: {exc}")
        # shell toggle-overview if it was bound to Super
        try:
            out2 = subprocess.run(["gsettings", "get", "org.gnome.shell.keybindings", "toggle-overview"],
                                  capture_output=True, text=True, timeout=2)
            if out2.returncode==0 and "'<Super" in out2.stdout:
                _saved_shell_toggle = out2.stdout.strip()
                subprocess.run(["gsettings", "set", "org.gnome.shell.keybindings", "toggle-overview", "@as []"],
                               capture_output=True, timeout=2)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _inhibit_overview: {exc}")
        try:
            print(f"[overview] inhibited overlay={_saved_overlay_key} shell={_saved_shell_toggle}", file=sys.stderr)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _inhibit_overview: {exc}")
        # start blocker for double Super
        try:
            _start_overview_block()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _inhibit_overview: {exc}")
    except Exception as e:
        try:
            print(f"[overview] inhibit failed {e}", file=sys.stderr)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in _inhibit_overview: {exc}")

def _restore_overview():
    global _saved_overlay_key, _saved_shell_toggle
    try:
        if _saved_overlay_key is not None:
            # restore exactly what was saved (including '' if user had it disabled)
            saved = _saved_overlay_key
            try:
                from gi.repository import Gio as _GioR
                _sr = _GioR.Settings.new("org.gnome.mutter")
                # saved is like "'Super'" or "''" — strip outer quotes for Gio
                if saved in ("''", ""):
                    _sr.set_string("overlay-key", "")
                else:
                    # remove leading/trailing single quotes
                    val = saved.strip()
                    if len(val) >= 2 and val[0] == "'" and val[-1] == "'":
                        val = val[1:-1]
                    _sr.set_string("overlay-key", val)
                _GioR.Settings.sync()
            except Exception as e:
                try:
                    print(f"[overview] restore Gio failed {e}", file=sys.stderr)
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in _restore_overview: {exc}")
            # also via subprocess/dconf for robustness
            try:
                subprocess.run(["gsettings", "set", "org.gnome.mutter", "overlay-key", saved],
                               capture_output=True, timeout=2)
                subprocess.run(["dconf", "write", "/org/gnome/mutter/overlay-key", saved],
                               capture_output=True, timeout=2)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _restore_overview: {exc}")
            # verify
            try:
                chk = subprocess.run(["gsettings", "get", "org.gnome.mutter", "overlay-key"],
                                     capture_output=True, text=True, timeout=2)
                print(f"[overview] restored overlay={saved} now={chk.stdout.strip() if chk.returncode==0 else chk.stderr.strip()}", file=sys.stderr)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _restore_overview: {exc}")
            _saved_overlay_key=None
        elif _daemon_app is not None:
            # Only daemon should auto-restore a leftover '' from a crash.
            # Short-lived ctl toggle clients also register this atexit and
            # would otherwise race with the daemon's inhibit (daemon sets ''
            # then client atexit sees '' and restores 'Super').
            try:
                cur = subprocess.run(["gsettings", "get", "org.gnome.mutter", "overlay-key"],
                                     capture_output=True, text=True, timeout=2)
                if cur.returncode==0 and cur.stdout.strip() == "''":
                    # no saved state — likely leftover inhibit from crash; restore default 'Super' via Gio too
                    try:
                        from gi.repository import Gio as _GioR2
                        _sr2 = _GioR2.Settings.new("org.gnome.mutter")
                        _sr2.set_string("overlay-key", "Super")
                        _GioR2.Settings.sync()
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _restore_overview: {exc}")
                    subprocess.run(["gsettings", "set", "org.gnome.mutter", "overlay-key", "'Super'"],
                                   capture_output=True, timeout=2)
                    subprocess.run(["dconf", "write", "/org/gnome/mutter/overlay-key", "'Super'"],
                                   capture_output=True, timeout=2)
                    print("[overview] restored (no saved) -> 'Super'", file=sys.stderr)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _restore_overview: {exc}")
        if _saved_shell_toggle is not None:
            try:
                subprocess.run(["gsettings", "set", "org.gnome.shell.keybindings", "toggle-overview", _saved_shell_toggle],
                               capture_output=True, timeout=2)
            except Exception:
                try:
                    subprocess.run(["gsettings", "reset", "org.gnome.shell.keybindings", "toggle-overview"],
                                   capture_output=True, timeout=2)
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in _restore_overview: {exc}")
            _saved_shell_toggle=None
            try:
                _stop_overview_block()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _restore_overview: {exc}")
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in _restore_overview: {exc}")
    try:
        _stop_overview_block()
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in _restore_overview: {exc}")
_overview_block_id = None
def _start_overview_block():
    global _overview_block_id
    try:
        if _overview_block_id is not None:
            return
        from gi.repository import GLib
        def _check():
            try:
                if not is_viewer_active():
                    return True
                # re-assert overlay-key stays '' while screensaver visible (guard external reset)
                try:
                    from gi.repository import Gio as _GioChk
                    _sc = _GioChk.Settings.new("org.gnome.mutter")
                    if _sc.get_string("overlay-key") != "":
                        _sc.set_string("overlay-key", "")
                        _GioChk.Settings.sync()
                        try:
                            subprocess.run(["gsettings", "set", "org.gnome.mutter", "overlay-key", "''"],
                                           capture_output=True, timeout=1)
                        except Exception as exc:
                            _dbg(f"Suppressed non-fatal exception in _check: {exc}")
                        print("[overview] re-asserted overlay='' (was non-empty)", file=sys.stderr)
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in _check: {exc}")
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _check: {exc}")
            return True
        _overview_block_id = GLib.timeout_add(180, _check)
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in _start_overview_block: {exc}")

def _stop_overview_block():
    global _overview_block_id
    try:
        if _overview_block_id is not None:
            from gi.repository import GLib
            try:
                GLib.source_remove(_overview_block_id)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _stop_overview_block: {exc}")
            _overview_block_id = None
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in _stop_overview_block: {exc}")

# Ensure overlay restored even on crash / SIGTERM
try:
    atexit.register(_restore_overview)
    atexit.register(_stop_overview_block)
except Exception as exc:
    _dbg(f"Suppressed non-fatal exception in module setup: {exc}")

def _daemon_switch_to_active_watch():
    """Arm Mutter's user-active watch in the daemon.

    Activity never closes the viewer anymore (Super+Q only), but a fired
    active watch is how the daemon learns dismissal happened (the child's
    hide runs in its own process with no _idle_proxy) and re-arms the idle
    watch so the screensaver auto-shows again after the next idle period.
    """
    try:
        if _idle_proxy is None:
            return
        from gi.repository import GLib, Gio
        if _idle_watch_ids.get("active") is None:
            try:
                res = _idle_proxy.call_sync("AddUserActiveWatch", None, Gio.DBusCallFlags.NONE, -1, None)
                _idle_watch_ids["active"] = res.unpack()[0]
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _daemon_switch_to_active_watch: {exc}")
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in _daemon_switch_to_active_watch: {exc}")

def _daemon_switch_to_idle_watch():
    try:
        if _idle_proxy is None:
            return
        from gi.repository import GLib, Gio
        if _idle_watch_ids.get("active") is not None:
            try:
                _idle_proxy.call_sync("RemoveWatch", GLib.Variant("(u)", (_idle_watch_ids["active"],)), Gio.DBusCallFlags.NONE, -1, None)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _daemon_switch_to_idle_watch: {exc}")
            _idle_watch_ids["active"]=None
        if _idle_watch_ids.get("idle") is None:
            try:
                import json, os
                # read current idle_seconds
                cfg=load_config()
                secs=int(cfg.get("idle_seconds",300))
                res=_idle_proxy.call_sync("AddIdleWatch", GLib.Variant("(t)", (secs*1000,)), Gio.DBusCallFlags.NONE, -1, None)
                _idle_watch_ids["idle"]=res.unpack()[0]
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _daemon_switch_to_idle_watch: {exc}")
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in _daemon_switch_to_idle_watch: {exc}")

def run_viewer(html_path, clock_format="24h", scene_options=None):
    """Viewer subprocess entry point — isolated WebKit, daemon stays 30M flat."""
    global _is_viewer_mode, _viewer_loop, _viewer_windows
    if not has_graphical_session():
        print("No graphical session available; cannot start screensaver viewer.", file=sys.stderr)
        return False
    _is_viewer_mode = True
    # Viewer handles its own SIGTERM/SIGINT to exit cleanly when daemon Hide kills it
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Gtk, GLib
        scene_name = os.path.basename(html_path)
        scene_options = config_store.get_scene_options(
            {"screensaver_options": {scene_name: scene_options or {}}}, scene_name
        )
        _viewer_windows = _create_viewer_windows(html_path, clock_format, scene_options)
        loop = GLib.MainLoop()
        _viewer_loop = loop
        def _viewer_sig(*_a):
            try:
                for w in list(_viewer_windows):
                    try:
                        w.close()
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _viewer_sig: {exc}")
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _viewer_sig: {exc}")
            try:
                loop.quit()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _viewer_sig: {exc}")
            return False
        try:
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _viewer_sig)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _viewer_sig)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, _viewer_sig)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in run_viewer: {exc}")
        loop.run()
    except Exception as e:
        print(f"Viewer failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    # ensure WebKit processes terminated before exit (so daemon's kill is not needed)
    try:
        for w in list(_viewer_windows):
            try:
                web = w.get_child()
                if web is not None:
                    try:
                        web.terminate_web_process()
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _viewer_sig: {exc}")
                    try:
                        web.run_dispose()
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _viewer_sig: {exc}")
                w.run_dispose()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _viewer_sig: {exc}")
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in run_viewer: {exc}")
    sys.exit(0)

def show_viewer():
    """Show screensaver viewer — daemon spawns isolated viewer subprocess (keeps daemon lean)."""
    global _viewer_windows, _is_showing, _viewer_process
    if _session_locked:
        _dbg("refused to show viewer while session is locked")
        return False
    # Stronger TOCTOU guard: claim the showing state and keep the flag set
    # until hide_viewer() or the child-watch cleanup clears it. The previous
    # finally-always-clear only protected the short spawn window and allowed
    # concurrent Show/Toggle races under D-Bus + timers.
    # Recover from stale _is_showing (child crashed / fallback never visible)
    # which previously left the daemon permanently blocked for both auto-idle
    # and manual Toggle.
    if is_viewer_active():
        return True
    if _is_showing:
        # Stale flag with no active viewer — clean up and allow retry
        try:
            if _viewer_process is not None:
                try:
                    if _viewer_process.poll() is None:
                        # child still alive but not yet visible (transient)
                        return True
                    _viewer_process = None
                except Exception:
                    _viewer_process = None
                    return True
            try:
                _uninhibit()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in show_viewer: {exc}")
            try:
                _restore_overview()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in show_viewer: {exc}")
            try:
                _cancel_lock()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in show_viewer: {exc}")
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in show_viewer: {exc}")
        _is_showing = False
    _is_showing = True
    cfg = load_config()
    html_path = get_active_html_path(cfg)
    if html_path is None:
        _is_showing = False
        return False
    clock_format = cfg.get("clock_format", "24h")
    scene_options = config_store.get_scene_options(cfg, os.path.basename(html_path))
    # If viewer subprocess already alive, treat as active
    if _viewer_process is not None:
        try:
            if _viewer_process.poll() is None:
                # Keep _is_showing True — viewer is live
                return True
            else:
                _viewer_process = None
        except Exception:
            _viewer_process = None
    try:
        _inhibit()
        _inhibit_overview()
        # Defensive: clear stale in-daemon windows (should be none with subprocess model)
        _viewer_windows = []
        # Spawn isolated viewer — daemon stays 30M, WebKit ~400M lives in child and is reaped on Hide
        try:
            _viewer_process = subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "viewer", html_path, clock_format, json.dumps(scene_options)],
                stdout=subprocess.DEVNULL, stderr=None,
                start_new_session=True)
        except Exception as e:
            print(f"Failed to spawn viewer subprocess: {e}", file=sys.stderr)
            # fallback to in-process (old path) if spawn fails
            _viewer_windows = _create_viewer_windows(html_path, clock_format, scene_options)
            _viewer_process = None
        _daemon_switch_to_active_watch()
        _schedule_lock()
        # GLib owns the child wait so the daemon does not poll every 500 ms.
        try:
            from gi.repository import GLib
            if _viewer_process is not None:
                watched_pid = _viewer_process.pid

                def _on_child_exit(pid, wait_status, _user_data=None):
                    global _is_showing, _viewer_process, _viewer_child_watch_id
                    _viewer_child_watch_id = None
                    if _viewer_process is None or _viewer_process.pid != pid:
                        return
                    try:
                        returncode = os.waitstatus_to_exitcode(wait_status)
                    except (AttributeError, ValueError):
                        returncode = 0 if wait_status == 0 else 1
                    # GLib has already reaped the process; populate Popen's
                    # cached status so later poll()/wait() calls do not wait again.
                    _viewer_process.returncode = returncode
                    _handle_viewer_exit(returncode)
                    _is_showing = False
                    _viewer_process = None
                    for cleanup in (_uninhibit, _restore_overview, _cancel_lock,
                                    _daemon_switch_to_idle_watch):
                        try:
                            cleanup()
                        except Exception as exc:
                            print(f"Viewer-exit cleanup failed ({cleanup.__name__}): {exc}",
                                  file=sys.stderr)

                _viewer_child_watch_id = GLib.child_watch_add(
                    GLib.PRIORITY_DEFAULT, watched_pid, _on_child_exit)
            else:
                # In-process fallback has no child to watch; retain a light
                # visibility check only for that exceptional path.
                def _watch_in_process_fallback():
                    global _is_showing
                    if _is_showing and not is_viewer_active():
                        _is_showing = False
                        for cleanup in (_uninhibit, _restore_overview, _cancel_lock,
                                        _daemon_switch_to_idle_watch):
                            try:
                                cleanup()
                            except Exception as exc:
                                print(f"Viewer cleanup failed ({cleanup.__name__}): {exc}",
                                      file=sys.stderr)
                        return False
                    return bool(is_viewer_active())
                GLib.timeout_add(500, _watch_in_process_fallback)
        except Exception as exc:
            print(f"Unable to register viewer-exit watch: {exc}", file=sys.stderr)
        # Success: leave _is_showing True until hide / child exit
        return True
    except Exception as e:
        print(f"Failed to show screensaver: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        _is_showing = False
        return False

def hide_viewer():
    """Hide/destroy viewer windows in this process. Thorough cleanup to prevent ghost dash/bwrap leak."""
    global _viewer_windows, _is_showing, _pending_sources, _ephemeral_ctx, _viewer_process, _viewer_child_watch_id, _is_viewer_mode, _viewer_loop
    if not _is_showing and not is_viewer_active():
        return False
    # Viewer subprocess: just close windows and exit, daemon handles inhibit/overlay via child watch
    if _is_viewer_mode:
        try:
            for w in list(_viewer_windows):
                try:
                    w.close()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            if _viewer_loop is not None:
                try:
                    _viewer_loop.quit()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        # also terminate WebKit quickly
        try:
            for w in list(_viewer_windows):
                try:
                    web = w.get_child()
                    if web is not None:
                        try:
                            web.terminate_web_process()
                        except Exception as exc:
                            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        try:
            import sys
            sys.exit(0)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        return True
    # Hide reaps synchronously, so remove GLib's competing child watch first.
    if _viewer_child_watch_id is not None:
        try:
            from gi.repository import GLib
            GLib.source_remove(_viewer_child_watch_id)
        except Exception as exc:
            print(f"Unable to remove viewer child watch before Hide: {exc}", file=sys.stderr)
        _viewer_child_watch_id = None
    # Daemon: if isolated viewer subprocess alive, terminate it (keeps daemon lean)
    if _viewer_process is not None:
        try:
            if _viewer_process.poll() is None:
                try:
                    # try graceful TERM to process group
                    try:
                        os.killpg(os.getpgid(_viewer_process.pid), signal.SIGTERM)
                    except Exception:
                        _viewer_process.terminate()
                    try:
                        _viewer_process.wait(timeout=2)
                    except Exception:
                        try:
                            os.killpg(os.getpgid(_viewer_process.pid), signal.SIGKILL)
                        except Exception:
                            try:
                                _viewer_process.kill()
                            except Exception as exc:
                                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            _viewer_process = None
        except Exception:
            _viewer_process = None
        # daemon inhibit/overlay cleanup (viewer subprocess already exited, but daemon inhibited)
        _is_showing = False
        try:
            _uninhibit()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        try:
            _restore_overview()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        try:
            _cancel_lock()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        try:
            _daemon_switch_to_idle_watch()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        try:
            _kill_orphan_webkit()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        try:
            import gc
            gc.collect()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        # also clear legacy in-daemon windows if any (fallback path)
        _viewer_windows = []
        return True
    # Cancel any pending fullscreen/gc sources from previous Show (leaked GLib sources)
    try:
        from gi.repository import GLib
        ctx = GLib.MainContext.default()
        for sid in list(_pending_sources):
            try:
                if ctx.find_source_by_id(sid) is not None:
                    GLib.source_remove(sid)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        _pending_sources.clear()
    except Exception:
        try:
            _pending_sources.clear()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    _is_showing = False
    to_close = list(_viewer_windows)
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        for tl in Gtk.Window.list_toplevels():
            try:
                if tl.get_title() == "Material Screensaver" and tl not in to_close:
                    to_close.append(tl)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    if not to_close:
        _viewer_windows = []
        _uninhibit()
        _restore_overview()
        _cancel_lock()
        _daemon_switch_to_idle_watch()
        # Ghost bwrap may remain even when no visible window — still kill (second-show ghost)
        try:
            _kill_orphan_webkit()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        try:
            import gc
            gc.collect()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        return False
    # Ungrab once before closing
    try:
        import gi
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk
        display = Gdk.Display.get_default()
        if display:
            try:
                display.get_default_seat().ungrab()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    for w in list(to_close):
        try:
            # Detach WebView first — crucial to let WebKit release bwrap/WebProcess
            web = None
            try:
                web = w.get_child()
            except Exception:
                web = None
            if web is not None:
                try:
                    # remove per-view UserStyleSheets we injected (prevents manager leak)
                    try:
                        ucm = web.get_user_content_manager()
                        ucm.remove_all_style_sheets()
                        ucm.remove_all_scripts()
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                try:
                    w.set_child(None)
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                try:
                    web.stop_loading()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                # Don't load about:blank — it spawns new navigation; just terminate
                try:
                    web.terminate_web_process()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                try:
                    web.unparent()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                try:
                    # GTK4: run_dispose frees underlying GObject and bwrap pipes (fixes Tasks leak)
                    web.run_dispose()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            # Remove from Gtk.Application if applicable (prevents ghost dash entry)
            try:
                if _daemon_app is not None:
                    _daemon_app.remove_window(w)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            try:
                w.close()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            try:
                w.set_visible(False)
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            # Drop ephemeral ctx reference to allow GC (fixes 30M per cycle creep)
            try:
                if hasattr(w, "_ephemeral_ctx"):
                    try:
                        # Clear ctx cache before dropping ref
                        c = getattr(w, "_ephemeral_ctx", None)
                        if c is not None:
                            try:
                                c.clear_cache()
                            except Exception as exc:
                                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                    try:
                        delattr(w, "_ephemeral_ctx")
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            try:
                w.run_dispose()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    _viewer_windows = []
    _uninhibit()
    _restore_overview()
    _cancel_lock()
    _daemon_switch_to_idle_watch()
    # Clear WebKit caches to prevent memory creep — both shared and ephemeral
    try:
        import gi
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit
        from gi.repository import GLib as _GLib
        for _ctx in [_shared_web_context, _ephemeral_ctx]:
            if _ctx is None:
                continue
            try:
                _ctx.clear_cache()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            try:
                mgr = _ctx.get_website_data_manager()
                if mgr is not None:
                    try:
                        mgr.clear(WebKit.WebsiteDataTypes.MEMORY_CACHE, _GLib.Variant("t", 0), None, None, None)
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                    try:
                        mgr.clear(WebKit.WebsiteDataTypes.DISK_CACHE, _GLib.Variant("t", 0), None, None, None)
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        # also try default context
        try:
            dctx = WebKit.WebContext.get_default()
            if dctx not in (_shared_web_context, _ephemeral_ctx):
                try:
                    dctx.clear_cache()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
        # drop ephemeral to fully free its NetworkProcess (trade ~30M create vs 38M retain)
        try:
            if _ephemeral_ctx is not None:
                try:
                    _ephemeral_ctx.clear_cache()
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
                _ephemeral_ctx = None
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    try:
        import gc
        gc.collect()
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    # Kill lingering orphans — btop ghost (also second-show ghost if shared NetworkProcess killed)
    try:
        if not is_viewer_active():
            _kill_orphan_webkit()
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib
        def _gc_once():
            try:
                import gc as _gc
                _gc.collect()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _gc_once: {exc}")
            try:
                import gi as _gi
                _gi.require_version("WebKit", "6.0")
                from gi.repository import WebKit as _Wk
                c = _shared_web_context or _Wk.WebContext.get_default()
                if c is not None:
                    try:
                        c.clear_cache()
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _gc_once: {exc}")
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _gc_once: {exc}")
            return False
        GLib.idle_add(_gc_once, priority=GLib.PRIORITY_LOW)
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in hide_viewer: {exc}")
    return True

# ---------- D-Bus delegation helpers ----------
def _daemon_is_available():
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        # Check if name is owned
        res = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "NameHasOwner",
            __import__("gi.repository.GLib", fromlist=["Variant"]).Variant("(s)", (SERVICE_NAME,)),
            None, 0, -1, None)
        return res.unpack()[0]
    except Exception:
        return False

def _call_daemon(method):
    """Call daemon method via D-Bus. Returns (success, result)."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.NONE, None,
            SERVICE_NAME, OBJECT_PATH, INTERFACE_NAME, None)
        if method == "IsActive":
            res = proxy.call_sync("IsActive", None, Gio.DBusCallFlags.NONE, -1, None)
            return True, res.unpack()[0]
        else:
            proxy.call_sync(method, None, Gio.DBusCallFlags.NONE, -1, None)
            return True, None
    except Exception as e:
        return False, str(e)

def is_running():
    """Cross-process check: daemon IsActive if available, else local."""
    # Try daemon first
    try:
        ok, res = _call_daemon("IsActive")
        if ok:
            return bool(res)
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in is_running: {exc}")
    return is_viewer_active()

def start():
    """Show screensaver. Delegates to daemon if running, else standalone viewer."""
    # Try daemon
    ok, _ = _call_daemon("Show")
    if ok:
        return
    if not has_graphical_session():
        print("No graphical session available; cannot start screensaver.", file=sys.stderr)
        sys.exit(1)
    # Fallback: standalone viewer (blocking)
    cfg = load_config()
    html_path = get_active_html_path(cfg)
    if html_path is None:
        sys.exit(1)
    clock_format = cfg.get("clock_format", "24h")
    # For standalone, we need to run a Gtk loop blocking — match show_viewer() ordering (inhibit before create)
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Gtk, GLib
        global _viewer_windows, _is_showing
        _is_showing = True
        _inhibit()
        _inhibit_overview()
        _viewer_windows = _create_viewer_windows(
            html_path, clock_format,
            config_store.get_scene_options(cfg, os.path.basename(html_path)),
        )
        _schedule_lock()
        # For standalone, run main loop until windows closed
        loop = GLib.MainLoop()
        # Also handle SIGTERM
        import signal
        def handle_sigterm(*a):
            hide_viewer()
            try:
                loop.quit()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in handle_sigterm: {exc}")
            return GLib.SOURCE_REMOVE
        try:
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, handle_sigterm)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in start: {exc}")
        loop.run()
        # hide_viewer already uninhibited; ensure cleanup even if loop exited without hide
        try:
            hide_viewer()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in start: {exc}")
        _is_showing = False
        _uninhibit()
        _restore_overview()
        _cancel_lock()
    except Exception as e:
        print(f"Failed to start screensaver viewer: {e}", file=sys.stderr)
        _is_showing = False
        sys.exit(1)

def stop():
    """Hide screensaver. Delegates to daemon if running."""
    ok, _ = _call_daemon("Hide")
    if ok:
        return
    # Fallback local
    hide_viewer()
    # If we were in standalone loop, the loop will quit via check_closed
    # But if called as separate `ctl stop` process while standalone viewer is in another process,
    # we can't affect that process's windows (different process). Need to find and kill that viewer process.
    # Try pkill fallback for standalone viewer — scoped to user and exact argv to avoid killing daemon/gui
    try:
        import getpass
        user = getpass.getuser()
        subprocess.run(["pkill", "-u", user, "-f", r"material-screensaver-ctl\.py start(\b| )"],
                       capture_output=True, timeout=2)
    except Exception:
        try:
            subprocess.run(["pkill", "-f", "material-screensaver-ctl.py start"], capture_output=True, timeout=2)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in stop: {exc}")

def toggle():
    # Use daemon atomic Toggle if available (avoids IsActive→Show race)
    ok, _ = _call_daemon("Toggle")
    if ok:
        return
    if is_viewer_active():
        hide_viewer()
    else:
        # The fallback must run a GTK main loop; creating windows and then
        # returning immediately destroys the viewer with this CLI process.
        start()

def run_daemon():
    if not has_graphical_session():
        print("No graphical session (WAYLAND_DISPLAY/DISPLAY unset); "
              "material-screensaver daemon exiting.", file=sys.stderr)
        sys.exit(0)

    import gi
    gi.require_version("Gio", "2.0")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Gio, GLib, Gtk, Gdk

    # Use Gtk.Application (required for Wayland fullscreen to map correctly, not Gtk.init + GLib loop)
    global _daemon_app
    app = Gtk.Application(application_id="io.github.sakib.MaterialScreensaver")
    _daemon_app = app
    # Hold to keep app running without windows
    try:
        app.hold()
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in run_daemon: {exc}")

    # Ensure overlay/hold cleaned on SIGTERM/SIGINT (systemd stop)
    try:
        def _sig_handler(*_a):
            # Tear down viewer first so overlay-key is restored while we still
            # have a live session, then release the application hold and quit.
            try:
                hide_viewer()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _sig_handler: {exc}")
            try:
                _restore_overview()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _sig_handler: {exc}")
            try:
                _uninhibit()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _sig_handler: {exc}")
            try:
                _cancel_lock()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _sig_handler: {exc}")
            try:
                app.release()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _sig_handler: {exc}")
            try:
                app.quit()
            except Exception as exc:
                _dbg(f"Suppressed non-fatal exception in _sig_handler: {exc}")
            return GLib.SOURCE_REMOVE
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _sig_handler)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _sig_handler)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, _sig_handler)
    except Exception as exc:
        _dbg(f"Suppressed non-fatal exception in run_daemon: {exc}")

    # Need to wait for app to be registered before getting display — use globals so manual Show/Hide can switch watches
    global _idle_proxy, _idle_watch_ids
    bus = None

    def setup_idle_watches():
        global _idle_proxy, _idle_watch_ids
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            _idle_proxy = Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.NONE, None,
                "org.gnome.Mutter.IdleMonitor",
                "/org/gnome/Mutter/IdleMonitor/Core",
                "org.gnome.Mutter.IdleMonitor", None,
            )
        except Exception as e:
            print(f"IdleMonitor proxy failed: {e}", file=sys.stderr)
            return

        def current_idle_seconds():
            return int(load_config().get("idle_seconds", 300))

        def remove_watch(kind):
            wid = _idle_watch_ids.get(kind)
            if wid is not None:
                try:
                    _idle_proxy.call_sync("RemoveWatch", GLib.Variant("(u)", (wid,)), Gio.DBusCallFlags.NONE, -1, None)
                except Exception as exc:
                    _dbg(f"Suppressed non-fatal exception in remove_watch: {exc}")
                _idle_watch_ids[kind] = None

        def add_idle_watch():
            # Idle and active watches are mutually exclusive: otherwise a stale
            # active watch can fire after unlock and race the newly armed idle watch.
            remove_watch("active")
            remove_watch("idle")
            if _session_locked:
                _dbg("idle watch not armed while session is locked")
                return False
            try:
                result = _idle_proxy.call_sync("AddIdleWatch", GLib.Variant("(t)", (current_idle_seconds() * 1000,)), Gio.DBusCallFlags.NONE, -1, None)
                _idle_watch_ids["idle"] = result.unpack()[0]
                return True
            except Exception as e:
                print(f"AddIdleWatch failed: {e}", file=sys.stderr)
                return False

        def add_active_watch():
            # Never leave an idle watch armed while the viewer is showing.
            remove_watch("idle")
            remove_watch("active")
            try:
                result = _idle_proxy.call_sync("AddUserActiveWatch", None, Gio.DBusCallFlags.NONE, -1, None)
                _idle_watch_ids["active"] = result.unpack()[0]
            except Exception as e:
                print(f"AddUserActiveWatch failed: {e}", file=sys.stderr)

        def on_signal(_proxy, _sender, signal_name, params):
            if signal_name != "WatchFired":
                return
            (fired_id,) = params.unpack()
            if fired_id == _idle_watch_ids["idle"]:
                # Ignore stale WatchFired events delivered during a session lock.
                if _session_locked:
                    _dbg("ignored idle WatchFired while session is locked")
                    return
                # Idle reached -> show. Arm the active watch so Super+Q/activity
                # re-arms the idle watch for the next cycle (it never closes).
                show_viewer()
                add_active_watch()
            elif fired_id == _idle_watch_ids["active"]:
                # Activity after showing (e.g. Super+Q in the child) -> re-arm
                # the idle watch for next time. Never dismisses here.
                add_idle_watch()

        try:
            _idle_proxy.connect("g-signal", on_signal)
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in setup_idle_watches: {exc}")
        add_idle_watch()
        # Re-read the idle timeout while the daemon is running. Settings writes
        # config.json directly; Mutter's existing idle watch does not update by
        # itself. Defer re-arming while the viewer is visible, then refresh the
        # watch as soon as the desktop is active again.
        last_idle_seconds = [current_idle_seconds()]

        def check_idle_config():
            try:
                current = current_idle_seconds()
                if _idle_watch_needs_refresh(
                    current, last_idle_seconds[0], _idle_watch_ids.get("idle"),
                    viewer_active=is_viewer_active(), session_locked=_session_locked,
                ):
                    if add_idle_watch():
                        last_idle_seconds[0] = current
            except Exception as exc:
                print(f"Failed to refresh idle timeout: {exc}", file=sys.stderr)
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add_seconds(2, check_idle_config)

        # Expose helpers for manual Show/Hide watch switching
        global _daemon_switch_to_active_watch, _daemon_switch_to_idle_watch
        _daemon_switch_to_active_watch = add_active_watch
        _daemon_switch_to_idle_watch = add_idle_watch

    # Setup watches on idle after app startup
    def on_startup(app):
        setup_idle_watches()
        # Monitor external locks (Super+L, loginctl, GNOME settings timer) so
        # the screensaver is dismissed instead of lingering after unlock.
        try:
            ss_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            ss_proxy = Gio.DBusProxy.new_sync(
                ss_bus, Gio.DBusProxyFlags.NONE, None,
                "org.gnome.ScreenSaver", "/org/gnome/ScreenSaver",
                "org.gnome.ScreenSaver", None)
            def _on_lock_signal(_proxy, _sender, sig, params):
                if sig == "ActiveChanged":
                    try:
                        (active,) = params.unpack()
                        _on_screen_saver_active_changed(active)
                    except Exception as exc:
                        print(f"Failed to process GNOME session lock signal: {exc}", file=sys.stderr)
            ss_proxy.connect("g-signal", _on_lock_signal)
            _dbg("subscribed to org.gnome.ScreenSaver ActiveChanged")
        except Exception as exc:
            print(f"Unable to monitor GNOME session lock state via org.gnome.ScreenSaver: {exc}", file=sys.stderr)
        # GNOME's ScreenSaver D-Bus name is not present in every modern session.
        # logind LockedHint provides an independent signal when that interface is absent.
        _monitor_login1_session_lock()
        # Re-create the viewer when the monitor topology changes while it is
        # showing (hotplug / docking). Hide then Show rebuilds one window per
        # current monitor. Debounced so a burst of items-changed doesn't
        # thrash.
        try:
            display = Gdk.Display.get_default()
            if display is not None:
                monitors = display.get_monitors()
                _mon_rebuild_id = {"id": None}

                def _rebuild_for_monitors(*_a):
                    _mon_rebuild_id["id"] = None
                    if not is_viewer_active():
                        return False
                    try:
                        hide_viewer()
                    except Exception as exc:
                        _dbg(f"Suppressed non-fatal exception in _rebuild_for_monitors: {exc}")
                    # small delay so the old process group is fully reaped
                    def _reshow():
                        try:
                            show_viewer()
                        except Exception as exc:
                            _dbg(f"Suppressed non-fatal exception in _reshow: {exc}")
                        return False
                    GLib.timeout_add(350, _reshow)
                    return False

                def _on_monitors_changed(*_a):
                    if not is_viewer_active():
                        return
                    # debounce
                    if _mon_rebuild_id["id"] is not None:
                        try:
                            GLib.source_remove(_mon_rebuild_id["id"])
                        except Exception as exc:
                            _dbg(f"Suppressed non-fatal exception in _on_monitors_changed: {exc}")
                    _mon_rebuild_id["id"] = GLib.timeout_add(400, _rebuild_for_monitors)

                try:
                    monitors.connect("items-changed", _on_monitors_changed)
                except Exception:
                    # older Gdk may not expose the signal on the list model
                    pass
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in on_startup: {exc}")
        # Own D-Bus name for delegation (same as before, but ensure app holds it)
        try:
            def on_bus_acquired(conn, name):
                try:
                    node_xml = f"""
                    <node>
                      <interface name="{INTERFACE_NAME}">
                        <method name="Show"/>
                        <method name="Hide"/>
                        <method name="Toggle"/>
                        <method name="IsActive">
                          <arg type="b" name="active" direction="out"/>
                        </method>
                      </interface>
                    </node>
                    """
                    from gi.repository import Gio as Gio3
                    node_info = Gio3.DBusNodeInfo.new_for_xml(node_xml)
                    iface_info = node_info.interfaces[0]
                    def on_method_call(conn, sender, path, iface, method, params, invocation):
                        try:
                            if method == "Show":
                                show_viewer()
                                invocation.return_value(None)
                            elif method == "Hide":
                                hide_viewer()
                                invocation.return_value(None)
                            elif method == "Toggle":
                                if is_viewer_active():
                                    hide_viewer()
                                else:
                                    show_viewer()
                                invocation.return_value(None)
                            elif method == "IsActive":
                                active = is_viewer_active()
                                invocation.return_value(GLib.Variant("(b)", (active,)))
                            else:
                                invocation.return_error_literal(Gio.DBusError, Gio.DBusError.UNKNOWN_METHOD, "Unknown method")
                        except Exception as e:
                            invocation.return_error_literal(Gio.DBusError, Gio.DBusError.FAILED, str(e))
                    conn.register_object(OBJECT_PATH, iface_info, on_method_call, None, None)
                except Exception as e:
                    print(f"Failed to export D-Bus object: {e}", file=sys.stderr)
            def on_name_acquired(conn, name):
                pass
            def on_name_lost(conn, name):
                pass
            Gio.bus_own_name(Gio.BusType.SESSION, SERVICE_NAME, Gio.BusNameOwnerFlags.NONE,
                on_bus_acquired, on_name_acquired, on_name_lost)
        except Exception as e:
            print(f"D-Bus own name failed: {e}", file=sys.stderr)

    def on_activate(app):
        pass

    app.connect("startup", on_startup)
    app.connect("activate", on_activate)

    # Use app.run (not register+GLib) — required for Wayland ApplicationWindow to map fullscreen correctly
    try:
        app.run(None)
    except Exception as e:
        print(f"app.run failed: {e}", file=sys.stderr)
        try:
            GLib.MainLoop().run()
        except Exception as exc:
            _dbg(f"Suppressed non-fatal exception in on_activate: {exc}")

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else None
    if action == "toggle":
        toggle()
    elif action == "start":
        start()
    elif action == "stop":
        stop()
    elif action == "daemon":
        run_daemon()
    elif action == "message":
        if len(sys.argv) == 3 and sys.argv[2] == "clear":
            update_lock_message("")
            print("Lock message cleared.")
        elif len(sys.argv) >= 4 and sys.argv[2] == "set":
            try:
                message = update_lock_message(" ".join(sys.argv[3:]))
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                sys.exit(2)
            print("Lock message cleared." if not message else "Lock message saved.")
        else:
            print("Usage: material-screensaver-ctl.py message set <text> | message clear",
                  file=sys.stderr)
            sys.exit(2)
    elif action == "viewer":
        # isolated viewer subprocess: viewer <html_path> [clock_format]
        hp = sys.argv[2] if len(sys.argv) > 2 else None
        cf = sys.argv[3] if len(sys.argv) > 3 else "24h"
        try:
            scene_options = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
        except (json.JSONDecodeError, TypeError, ValueError):
            scene_options = {}
        if not isinstance(scene_options, dict):
            scene_options = {}
        if hp is None:
            print("viewer requires html_path", file=sys.stderr)
            sys.exit(1)
        if run_viewer(hp, cf, scene_options) is False:
            sys.exit(1)
    else:
        sys.exit(__doc__)
