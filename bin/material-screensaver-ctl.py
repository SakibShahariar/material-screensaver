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
DEFAULT_CONFIG = {"active": None, "idle_seconds": 300, "clock_format": "24h", "random": False, "browser": "auto"}

# D-Bus service for daemon delegation (PID file gone)
SERVICE_NAME = "io.github.sakib.MaterialScreensaver"
OBJECT_PATH = "/io/github/sakib/MaterialScreensaver"
INTERFACE_NAME = "io.github.sakib.MaterialScreensaver"

# Viewer state (daemon or standalone)
_viewer_windows = []  # list[Gtk.Window]
_viewer_inhibit_cookie = None
_viewer_inhibit_proxy = None
_daemon_app = None  # Gtk.Application for daemon (Wayland fullscreen needs ApplicationWindow)


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
def _create_viewer_windows(html_path, clock_format="24h"):
    """Create one fullscreen Gtk.Window per monitor with WebKit WebView."""
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Gtk, Gdk, WebKit, GLib

    # Ensure Gtk initialized (no-op if already)
    # Gtk.init() not needed for Gtk4 Application, but safe for daemon GLib loop
    # Use Gdk.Display to enumerate monitors
    display = Gdk.Display.get_default()
    if display is None:
        # fallback: try default
        try:
            Gtk.init()
            display = Gdk.Display.get_default()
        except Exception:
            display = None

    monitors = []
    if display is not None:
        try:
            # Gdk.Display.get_monitors() is Gio.ListModel
            lm = display.get_monitors()
            n = lm.get_n_items()
            for i in range(n):
                monitors.append(lm.get_item(i))
        except Exception:
            pass
    if not monitors:
        monitors = [None]  # single window fallback

    uri = f"file://{html_path}?format={clock_format}"
    windows = []
    for mon in monitors:
        # Use ApplicationWindow when daemon app exists (Wayland needs app for proper fullscreen/layer)
        try:
            if _daemon_app is not None:
                win = Gtk.ApplicationWindow(application=_daemon_app, title="Material Screensaver")
            else:
                win = Gtk.Window(title="Material Screensaver")
        except Exception:
            win = Gtk.Window(title="Material Screensaver")
        win.set_decorated(False)
        win.set_default_size(1920, 1080)
        # Make fullscreen on that monitor
        # GTK4 fullscreen is per-window, compositor picks monitor where window is placed
        # For per-monitor, we can fullscreen each window; compositor will map each to a monitor if possible
        # Add CSS to hide cursor (also html has cursor:none)
        try:
            win.add_css_class("screensaver-window")
        except Exception:
            pass

        web = WebKit.WebView()
        settings = web.get_settings()
        try:
            settings.set_allow_file_access_from_file_urls(True)
            settings.set_allow_universal_access_from_file_urls(True)
            settings.set_enable_write_console_messages_to_stdout(False)
            settings.set_enable_javascript(True)
        except Exception:
            pass

        web.load_uri(uri)

        # Hide cursor via blank cursor after present (also CSS does)
        win.set_child(web)

        # Input handling: any key/motion/button should hide (for standalone; daemon also handles via IdleMonitor)
        def on_key(ctrl, keyval, keycode, state):
            # Esc also hides, any key hides
            hide_viewer()
            return True
        def on_click(ctrl, n_press, x, y):
            hide_viewer()
            return
        def on_motion(ctrl, x, y):
            # Optional: could require movement threshold; for now any motion after 500ms hides
            # To avoid immediate hide on show, check elapsed
            try:
                if getattr(win, "_show_time", 0) and (GLib.get_monotonic_time() - win._show_time) < 500_000:
                    return
            except Exception:
                pass
            # Don't hide on tiny jitter if daemon will handle via IdleMonitor? For now hide to allow standalone dismiss
            # In daemon mode, IdleMonitor's AddUserActiveWatch will also fire, but double hide is okay
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

        # Ensure window covers monitor geometry before fullscreen
        try:
            if mon is not None:
                geom = mon.get_geometry()
                win.set_default_size(geom.width, geom.height)
        except Exception:
            pass
        # Hide from taskbar/dash where possible (best effort)
        try:
            win.set_hide_on_close(False)
        except Exception:
            pass

        # Present and fullscreen (order matters on Wayland: present first, then fullscreen)
        win.present()
        try:
            win.fullscreen()
        except Exception:
            pass
        # Ensure visible and on top
        try:
            win.set_visible(True)
        except Exception:
            pass

        # Record show time for motion grace
        try:
            win._show_time = GLib.get_monotonic_time()
        except Exception:
            pass

        # Seat grab (best effort, may fail on Wayland)
        try:
            seat = display.get_default_seat() if display else None
            if seat and win.get_surface():
                # Gdk.Seat.grab requires surface and capabilities
                seat.grab(win.get_surface(), Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        except Exception:
            pass

        windows.append(win)

    return windows


def is_viewer_active():
    """Local check (no D-Bus). True if we have visible viewer windows in this process."""
    global _viewer_windows
    # Check tracked windows first
    for w in list(_viewer_windows):
        try:
            if w.get_visible():
                return True
        except Exception:
            continue
    # Fallback: check any toplevel ghost windows
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
    return False


def show_viewer():
    """Show screensaver viewer in this process (non-blocking, creates windows)."""
    global _viewer_windows
    if is_viewer_active():
        return True
    cfg = load_config()
    html_path = get_active_html_path(cfg)
    clock_format = cfg.get("clock_format", "24h")
    try:
        _viewer_windows = _create_viewer_windows(html_path, clock_format)
        _inhibit()
        return True
    except Exception as e:
        print(f"Failed to show screensaver: {e}", file=sys.stderr)
        return False


def hide_viewer():
    """Hide/destroy viewer windows in this process."""
    global _viewer_windows
    # Also collect any orphaned toplevels (ghost windows not in _viewer_windows)
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
        return False
    for w in list(to_close):
        try:
            # ungrab seat
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
            # Stop WebView loading before close
            try:
                child = w.get_child()
                if child is not None:
                    try:
                        child.stop_loading()
                    except Exception:
                        pass
                    try:
                        child.load_uri("about:blank")
                    except Exception:
                        pass
                    try:
                        child.terminate_web_process()
                    except Exception:
                        pass
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
            try:
                child = w.get_child()
                if child is not None:
                    try:
                        w.set_child(None)
                    except Exception:
                        pass
                    try:
                        child.unparent()
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass
    _viewer_windows = []
    _uninhibit()
    try:
        import gc
        gc.collect()
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

    # Need to wait for app to be registered before getting display
    # Use idle to setup D-Bus and watches after app activation
    bus = None
    proxy_idle = None
    watch_ids = {"idle": None, "active": None}

    def setup_idle_watches():
        nonlocal bus, proxy_idle
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy_idle = Gio.DBusProxy.new_sync(
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
            wid = watch_ids.get(kind)
            if wid is not None:
                try:
                    proxy_idle.call_sync("RemoveWatch", GLib.Variant("(u)", (wid,)), Gio.DBusCallFlags.NONE, -1, None)
                except Exception:
                    pass
                watch_ids[kind] = None

        def add_idle_watch():
            remove_watch("idle")
            try:
                result = proxy_idle.call_sync("AddIdleWatch", GLib.Variant("(t)", (current_idle_seconds() * 1000,)), Gio.DBusCallFlags.NONE, -1, None)
                watch_ids["idle"] = result.unpack()[0]
            except Exception as e:
                print(f"AddIdleWatch failed: {e}", file=sys.stderr)

        def add_active_watch():
            remove_watch("active")
            try:
                result = proxy_idle.call_sync("AddUserActiveWatch", None, Gio.DBusCallFlags.NONE, -1, None)
                watch_ids["active"] = result.unpack()[0]
            except Exception as e:
                print(f"AddUserActiveWatch failed: {e}", file=sys.stderr)

        def on_signal(_proxy, _sender, signal_name, params):
            if signal_name != "WatchFired":
                return
            (fired_id,) = params.unpack()
            if fired_id == watch_ids["idle"]:
                show_viewer()
                add_active_watch()
            elif fired_id == watch_ids["active"]:
                hide_viewer()
                add_idle_watch()

        try:
            proxy_idle.connect("g-signal", on_signal)
        except Exception:
            pass
        add_idle_watch()

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
