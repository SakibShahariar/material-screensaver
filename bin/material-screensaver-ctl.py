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
import random
import subprocess

SCREENSAVER_DIR = os.path.expanduser("~/.local/share/material-screensaver/screensavers")
CONFIG_PATH = os.path.expanduser("~/.config/material-screensaver/config.json")
DEFAULT_CONFIG = {"active": None, "idle_seconds": 300, "clock_format": "24h", "random": False, "browser": "auto", "lock_after_seconds": 300}

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


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def list_screensavers():
    """Returns {filename: full_path} for every .html file in the screensavers dir."""
    paths = sorted(glob.glob(os.path.join(SCREENSAVER_DIR, "*.html")))
    return {os.path.basename(p): p for p in paths}


def get_active_html_path(cfg):
    screensavers = list_screensavers()
    if not screensavers:
        sys.exit(f"No screensaver .html files found in {SCREENSAVER_DIR}")
    if cfg.get("random", False):
        return random.choice(list(screensavers.values()))
    active = cfg.get("active")
    if active and active in screensavers:
        return screensavers[active]
    return next(iter(screensavers.values()))  # alphabetically first


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

def _inhibit():
    global _viewer_inhibit_cookie, _viewer_inhibit_proxy
    if _viewer_inhibit_cookie is not None:
        return
    proxy = _get_session_proxy()
    if proxy is None:
        return
    try:
        from gi.repository import GLib
        # flags 8 = inhibit idle, reason visible in gnome logs
        res = proxy.call_sync("Inhibit",
            GLib.Variant("(susu)", ("material-screensaver", 0, "Screensaver active", 8)),
            0, -1, None)
        _viewer_inhibit_cookie = res.unpack()[0]
        _viewer_inhibit_proxy = proxy
    except Exception:
        pass

def _uninhibit():
    global _viewer_inhibit_cookie, _viewer_inhibit_proxy
    if _viewer_inhibit_cookie is None or _viewer_inhibit_proxy is None:
        return
    try:
        from gi.repository import GLib
        _viewer_inhibit_proxy.call_sync("Uninhibit",
            GLib.Variant("(u)", (_viewer_inhibit_cookie,)), 0, -1, None)
    except Exception:
        pass
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
        except Exception:
            pass
    except Exception:
        _shared_web_context = None
    return _shared_web_context

def _kill_orphan_webkit():
    """Kill any lingering bwrap/WebKit children of this daemon (ghost btop). Returns count killed."""
    try:
        import os, signal, subprocess
        out = subprocess.run(["ps", "--ppid", str(os.getpid()), "-o", "pid=,args="],
                             capture_output=True, text=True, timeout=2)
        killed=0
        for line in out.stdout.splitlines():
            line=line.strip()
            if not line:
                continue
            parts=line.split(None,1)
            try:
                pid=int(parts[0])
            except Exception:
                continue
            cmd=parts[1] if len(parts)>1 else ""
            if "WebKitNetworkProcess" in cmd or "WebKitWebProcess" in cmd or ("bwrap" in cmd and "xdg-dbus-proxy" in cmd):
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed+=1
                except Exception:
                    pass
        return killed
    except Exception:
        return 0

def _create_viewer_windows(html_path, clock_format="24h"):
    """Create one fullscreen Gtk.Window per monitor with WebKit WebView."""
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Gtk, Gdk, WebKit, GLib

    # Always clean orphans before create — second Show often ghosts if previous Hide left bwrap
    # is_viewer_active is false when ghost is invisible, so we need explicit orphan check
    try:
        # If any WebKit child still alive while we think hidden, kill it before new Show
        import subprocess, os
        out = subprocess.run(["ps", "--ppid", str(os.getpid()), "-o", "args="],
                             capture_output=True, text=True, timeout=2)
        if "WebKit" in out.stdout or "bwrap" in out.stdout:
            _kill_orphan_webkit()
            import time
            time.sleep(0.15)
        if is_viewer_active():
            hide_viewer()
            import time
            time.sleep(0.05)
    except Exception:
        pass

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
        except Exception:
            pass
    if not monitors:
        monitors = [None]

    uri = f"file://{html_path}?format={clock_format}"
    windows = []
    # Ephemeral per Show — allows full cleanup after Hide and avoids reusing killed shared NetworkProcess (second-show ghost)
    try:
        ctx = WebKit.WebContext.new_ephemeral()
        try:
            ctx.set_cache_model(WebKit.CacheModel.DOCUMENT_VIEWER)
        except Exception:
            pass
    except Exception:
        ctx = _get_shared_context()
    _ephemeral_ctx = ctx
    for mon in monitors:
        try:
            if _daemon_app is not None:
                win = Gtk.ApplicationWindow(application=_daemon_app, title="Material Screensaver")
            else:
                win = Gtk.Window(title="Material Screensaver")
        except Exception:
            win = Gtk.Window(title="Material Screensaver")
        win.set_decorated(False)
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
        except Exception:
            pass

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
            settings.set_allow_file_access_from_file_urls(True)
            settings.set_allow_universal_access_from_file_urls(True)
            settings.set_enable_write_console_messages_to_stdout(False)
            settings.set_enable_javascript(True)
            # Prevent WebKit throttling when window is not focused (ghost 0.1% vs 87% fix)
            try:
                settings.set_enable_back_forward_navigation_gestures(False)
            except Exception:
                pass
        except Exception:
            pass
        web.load_uri(uri)
        win.set_child(web)

        def on_key(ctrl, keyval, keycode, state, _win=win):
            hide_viewer()
            return True
        def on_click(ctrl, n_press, x, y, _win=win):
            hide_viewer()
            return
        def on_motion(ctrl, x, y, _win=win):
            try:
                if getattr(_win, "_show_time", 0) and (GLib.get_monotonic_time() - _win._show_time) < 500_000:
                    return
            except Exception:
                pass
            hide_viewer()
            return
        try:
            key_ctrl = Gtk.EventControllerKey()
            key_ctrl.connect("key-pressed", on_key)
            win.add_controller(key_ctrl)
            click = Gtk.GestureClick()
            click.connect("pressed", on_click)
            win.add_controller(click)
            motion = Gtk.EventControllerMotion()
            motion.connect("motion", on_motion)
            win.add_controller(motion)
        except Exception:
            pass

        try:
            win.set_hide_on_close(False)
        except Exception:
            pass

        # Wayland: present must happen after app is active and surface realized.
        # Using `present()` then `fullscreen()` immediately can create ghost (dash visible, WebProcess 0.1% throttled).
        # Fix: present now, fullscreen on idle after surface mapped. Also connect to map for fallback.
        def _do_fullscreen(w=win, d=display):
            try:
                w.fullscreen()
            except Exception:
                pass
            try:
                w.set_visible(True)
            except Exception:
                pass
            try:
                w._show_time = GLib.get_monotonic_time()
            except Exception:
                pass
            # Seat grab after fullscreen (Wayland may fail — best effort)
            try:
                seat = d.get_default_seat() if d else None
                surf = w.get_surface()
                if seat and surf:
                    seat.grab(surf, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
            except Exception:
                pass
            return False

        # Present immediately (required to create surface)
        try:
            win.present()
        except Exception:
            try:
                win.set_visible(True)
            except Exception:
                pass
        # Defer fullscreen to next idle so Wayland compositor has surface
        try:
            GLib.idle_add(_do_fullscreen, priority=GLib.PRIORITY_HIGH_IDLE)
            # Retry after 200ms — second Show sometimes ghosts if first hide SIGTERM left compositor state stale
            def _retry_fs(w=win):
                try:
                    if w.get_visible() and not w.is_visible() or True:
                        w.fullscreen()
                        w.present()
                except Exception:
                    pass
                return False
            GLib.timeout_add(200, _retry_fs)
            GLib.timeout_add(600, _retry_fs)
        except Exception:
            _do_fullscreen()
        # Also ensure fullscreen on map (covers case where idle fired before map)
        try:
            def _on_map(w, _pspec=None):
                try:
                    w.fullscreen()
                    w.present()
                except Exception:
                    pass
                return False
            win.connect("map", _on_map)
        except Exception:
            pass

        # keep ephemeral ctx ref on window to prevent early GC
        try:
            win._ephemeral_ctx = _ephemeral_ctx
        except Exception:
            pass
        windows.append(win)

    return windows


def is_viewer_active():
    """Local check (no D-Bus). True if we have visible viewer windows in this process."""
    global _viewer_windows
    for w in list(_viewer_windows):
        try:
            if w.get_visible():
                return True
        except Exception:
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
            except Exception:
                continue
    except Exception:
        pass
    # Last resort: if any WebKit bwrap child still alive while we think hidden,
    # treat as active ghost (prevents Show from spawning duplicate that stays throttled)
    # We don't check here to avoid false positives during normal hide, but hide_viewer will clean anyway
    return False


def _lock_screen():
    """Lock GNOME session — used after screensaver has been visible for lock_after_seconds."""
    try:
        # Try GNOME ScreenSaver first
        subprocess.run(["gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
                        "--object-path", "/org/gnome/ScreenSaver",
                        "--method", "org.gnome.ScreenSaver.Lock"],
                       capture_output=True, timeout=3)
        return
    except Exception:
        pass
    try:
        subprocess.run(["loginctl", "lock-session"], capture_output=True, timeout=3)
    except Exception:
        pass
    try:
        subprocess.run(["xdg-screensaver", "lock"], capture_output=True, timeout=3)
    except Exception:
        pass

def _schedule_lock():
    global _lock_timeout_id
    try:
        if _lock_timeout_id is not None:
            try:
                from gi.repository import GLib
                GLib.source_remove(_lock_timeout_id)
            except Exception:
                pass
            _lock_timeout_id=None
        cfg=load_config()
        secs=int(cfg.get("lock_after_seconds", 300) or 0)
        if secs <=0:
            return
        if not is_viewer_active():
            return
        from gi.repository import GLib
        def _do_lock():
            global _lock_timeout_id
            _lock_timeout_id=None
            if is_viewer_active():
                _lock_screen()
            return False
        _lock_timeout_id = GLib.timeout_add_seconds(secs, _do_lock)
    except Exception:
        pass

def _cancel_lock():
    global _lock_timeout_id
    try:
        if _lock_timeout_id is not None:
            from gi.repository import GLib
            try:
                GLib.source_remove(_lock_timeout_id)
            except Exception:
                pass
            _lock_timeout_id=None
    except Exception:
        pass

def _daemon_switch_to_active_watch():
    """If daemon IdleMonitor is active, switch idle→active so mouse movement hides even manual Show."""
    try:
        if _idle_proxy is None:
            return
        from gi.repository import GLib, Gio
        # remove idle, add active
        if _idle_watch_ids.get("idle") is not None:
            try:
                _idle_proxy.call_sync("RemoveWatch", GLib.Variant("(u)", (_idle_watch_ids["idle"],)), Gio.DBusCallFlags.NONE, -1, None)
            except Exception:
                pass
            _idle_watch_ids["idle"]=None
        if _idle_watch_ids.get("active") is None:
            try:
                res=_idle_proxy.call_sync("AddUserActiveWatch", None, Gio.DBusCallFlags.NONE, -1, None)
                _idle_watch_ids["active"]=res.unpack()[0]
            except Exception:
                pass
    except Exception:
        pass

def _daemon_switch_to_idle_watch():
    try:
        if _idle_proxy is None:
            return
        from gi.repository import GLib, Gio
        if _idle_watch_ids.get("active") is not None:
            try:
                _idle_proxy.call_sync("RemoveWatch", GLib.Variant("(u)", (_idle_watch_ids["active"],)), Gio.DBusCallFlags.NONE, -1, None)
            except Exception:
                pass
            _idle_watch_ids["active"]=None
        if _idle_watch_ids.get("idle") is None:
            try:
                import json, os
                # read current idle_seconds
                cfg=load_config()
                secs=int(cfg.get("idle_seconds",300))
                res=_idle_proxy.call_sync("AddIdleWatch", GLib.Variant("(t)", (secs*1000,)), Gio.DBusCallFlags.NONE, -1, None)
                _idle_watch_ids["idle"]=res.unpack()[0]
            except Exception:
                pass
    except Exception:
        pass

def show_viewer():
    """Show screensaver viewer in this process (non-blocking, creates windows)."""
    global _viewer_windows
    if is_viewer_active():
        return True
    cfg = load_config()
    html_path = get_active_html_path(cfg)
    clock_format = cfg.get("clock_format", "24h")
    try:
        # Defensive: clear stale refs before creating new (ghost prevention)
        _viewer_windows = []
        _viewer_windows = _create_viewer_windows(html_path, clock_format)
        _inhibit()
        _daemon_switch_to_active_watch()
        _schedule_lock()
        return True
    except Exception as e:
        print(f"Failed to show screensaver: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def hide_viewer():
    """Hide/destroy viewer windows in this process. Thorough cleanup to prevent ghost dash/bwrap leak."""
    global _viewer_windows
    to_close = list(_viewer_windows)
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        for tl in Gtk.Window.list_toplevels():
            try:
                if tl.get_title() == "Material Screensaver" and tl not in to_close:
                    to_close.append(tl)
            except Exception:
                pass
    except Exception:
        pass
    if not to_close:
        _viewer_windows = []
        _uninhibit()
        _cancel_lock()
        _daemon_switch_to_idle_watch()
        # Ghost bwrap may remain even when no visible window — still kill (second-show ghost)
        try:
            _kill_orphan_webkit()
        except Exception:
            pass
        try:
            import gc
            gc.collect()
        except Exception:
            pass
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
            except Exception:
                pass
    except Exception:
        pass
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
                    w.set_child(None)
                except Exception:
                    pass
                try:
                    web.stop_loading()
                except Exception:
                    pass
                # Don't load about:blank — it spawns new navigation; just terminate
                try:
                    web.terminate_web_process()
                except Exception:
                    pass
                try:
                    web.unparent()
                except Exception:
                    pass
                try:
                    # GTK4: run_dispose frees underlying GObject and bwrap pipes (fixes Tasks leak)
                    web.run_dispose()
                except Exception:
                    pass
            # Remove from Gtk.Application if applicable (prevents ghost dash entry)
            try:
                if _daemon_app is not None:
                    _daemon_app.remove_window(w)
            except Exception:
                pass
            try:
                w.close()
            except Exception:
                pass
            try:
                w.set_visible(False)
            except Exception:
                pass
            # Drop ephemeral ctx reference to allow GC (fixes 30M per cycle creep)
            try:
                if hasattr(w, "_ephemeral_ctx"):
                    try:
                        # Clear ctx cache before dropping ref
                        c = getattr(w, "_ephemeral_ctx", None)
                        if c is not None:
                            try:
                                c.clear_cache()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        delattr(w, "_ephemeral_ctx")
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                w.run_dispose()
            except Exception:
                pass
        except Exception:
            pass
    _viewer_windows = []
    _uninhibit()
    _cancel_lock()
    _daemon_switch_to_idle_watch()
    # Clear WebKit caches to prevent memory creep
    try:
        import gi
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit
        from gi.repository import GLib as _GLib
        ctx = _shared_web_context
        if ctx is None:
            try:
                ctx = WebKit.WebContext.get_default()
            except Exception:
                ctx = None
        if ctx is not None:
            try:
                ctx.clear_cache()
            except Exception:
                pass
            try:
                mgr = ctx.get_website_data_manager()
                if mgr is not None:
                    try:
                        mgr.clear(WebKit.WebsiteDataTypes.MEMORY_CACHE, _GLib.Variant("t", 0), None, None, None)
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass
    try:
        import gc
        gc.collect()
    except Exception:
        pass
    # Kill lingering orphans — btop ghost (also second-show ghost if shared NetworkProcess killed)
    try:
        if not is_viewer_active():
            _kill_orphan_webkit()
    except Exception:
        pass
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib
        def _gc_once():
            try:
                import gc as _gc
                _gc.collect()
            except Exception:
                pass
            try:
                import gi as _gi
                _gi.require_version("WebKit", "6.0")
                from gi.repository import WebKit as _Wk
                c = _shared_web_context or _Wk.WebContext.get_default()
                if c is not None:
                    try:
                        c.clear_cache()
                    except Exception:
                        pass
            except Exception:
                pass
            return False
        GLib.idle_add(_gc_once, priority=GLib.PRIORITY_LOW)
    except Exception:
        pass
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
    except Exception:
        pass
    return is_viewer_active()


def start():
    """Show screensaver. Delegates to daemon if running, else standalone viewer."""
    # Try daemon
    ok, _ = _call_daemon("Show")
    if ok:
        return
    # Fallback: standalone viewer (blocking)
    cfg = load_config()
    html_path = get_active_html_path(cfg)
    clock_format = cfg.get("clock_format", "24h")
    # For standalone, we need to run a Gtk loop blocking
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Gtk, GLib
        # Create windows and run
        global _viewer_windows
        _viewer_windows = _create_viewer_windows(html_path, clock_format)
        _inhibit()
        # For standalone, run main loop until windows closed
        loop = GLib.MainLoop()
        # Poll for windows closed
        def check_closed():
            if not is_viewer_active():
                loop.quit()
                return False
            return True
        GLib.timeout_add(200, check_closed)
        # Also handle SIGTERM
        import signal
        def handle_sigterm(*a):
            hide_viewer()
            try:
                loop.quit()
            except Exception:
                pass
        try:
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, handle_sigterm)
        except Exception:
            pass
        loop.run()
        _uninhibit()
    except Exception as e:
        print(f"Failed to start screensaver viewer: {e}", file=sys.stderr)
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
    # Try pkill fallback for standalone viewer
    try:
        # Find standalone viewer processes (material-screensaver-ctl.py start) and SIGTERM them
        # Use pkill pattern; best effort
        subprocess.run(["pkill", "-f", "material-screensaver-ctl.py start"], capture_output=True)
    except Exception:
        pass


def toggle():
    if is_running():
        stop()
    else:
        start()


def run_daemon():
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
    except Exception:
        pass

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
                except Exception:
                    pass
                _idle_watch_ids[kind] = None

        def add_idle_watch():
            remove_watch("idle")
            try:
                result = _idle_proxy.call_sync("AddIdleWatch", GLib.Variant("(t)", (current_idle_seconds() * 1000,)), Gio.DBusCallFlags.NONE, -1, None)
                _idle_watch_ids["idle"] = result.unpack()[0]
            except Exception as e:
                print(f"AddIdleWatch failed: {e}", file=sys.stderr)

        def add_active_watch():
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
                show_viewer()
                add_active_watch()
            elif fired_id == _idle_watch_ids["active"]:
                hide_viewer()
                add_idle_watch()

        try:
            _idle_proxy.connect("g-signal", on_signal)
        except Exception:
            pass
        add_idle_watch()
        # Expose helpers for manual Show/Hide watch switching
        global _daemon_switch_to_active_watch, _daemon_switch_to_idle_watch
        _daemon_switch_to_active_watch = add_active_watch
        _daemon_switch_to_idle_watch = add_idle_watch

    # Setup watches on idle after app startup
    def on_startup(app):
        setup_idle_watches()
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
        except Exception:
            pass


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
    else:
        sys.exit(__doc__)
