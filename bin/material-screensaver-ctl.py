#!/usr/bin/env python3
"""
Control script for the Material screensaver.

Usage:
  material-screensaver-ctl.py toggle   # start it if not running, stop it if running
  material-screensaver-ctl.py start    # force start
  material-screensaver-ctl.py stop     # force stop
  material-screensaver-ctl.py daemon   # run the idle-watching loop (used by the systemd service)

All settings (active screensaver, idle timeout, browser choice) are read from
~/.config/material-screensaver/config.json, which the GUI app writes to.
Sensible defaults are used if that file doesn't exist yet.
"""
import os
import sys
import json
import glob
import signal
import random
import subprocess

SCREENSAVER_DIR = os.path.expanduser("~/.local/share/material-screensaver/screensavers")
CONFIG_PATH = os.path.expanduser("~/.config/material-screensaver/config.json")
PID_FILE = os.path.expanduser("~/.cache/material-screensaver.pid")

DEFAULT_CONFIG = {"active": None, "idle_seconds": 300, "browser": "auto", "clock_format": "24h", "random": False}

CHROMIUM_LIKE = {"helium", "helium-browser", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser"}
FIREFOX_LIKE = {"firefox"}
BROWSER_ORDER = ["firefox", "helium", "helium-browser", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser"]
PROFILE_ROOT = os.path.expanduser("~/.cache/material-screensaver")


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


def browser_cmd(browser, html_path, url_suffix):
    # a dedicated profile dir forces a brand-new process even if the browser
    # is already running elsewhere with the user's normal profile — without
    # this, --kiosk gets silently ignored and the URL just opens as a tab
    # in whatever window is already open (the single-instance IPC gotcha)
    profile_dir = os.path.join(PROFILE_ROOT, f"profile-{browser}")
    os.makedirs(profile_dir, exist_ok=True)
    url = f"file://{html_path}{url_suffix}"
    if browser in CHROMIUM_LIKE:
        return [
            browser, "--kiosk", f"--user-data-dir={profile_dir}",
            "--no-first-run", "--disable-session-crashed-bubble",
            url,
        ]
    if browser in FIREFOX_LIKE:
        return [
            browser, "--no-remote", "--new-instance",
            "-profile", profile_dir, "-kiosk",
            url,
        ]
    sys.exit(f"Don't know how to launch browser: {browser}")


def pick_browser_cmd(cfg, html_path):
    clock_format = cfg.get("clock_format", "24h")
    url_suffix = f"?format={clock_format}"
    choice = cfg.get("browser", "auto")
    candidates = [choice] if choice != "auto" and choice in (CHROMIUM_LIKE | FIREFOX_LIKE) else BROWSER_ORDER
    for browser in candidates:
        if subprocess.run(["which", browser], capture_output=True).returncode == 0:
            return browser_cmd(browser, html_path, url_suffix)
    sys.exit("No supported browser found (tried firefox, helium, chromium, chrome, brave). Install one of these.")


def read_pid():
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # raises if not alive
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        return None


def is_running():
    return read_pid() is not None


def start():
    if is_running():
        return
    cfg = load_config()
    html_path = get_active_html_path(cfg)
    cmd = pick_browser_cmd(cfg, html_path)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))


def stop():
    pid = read_pid()
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def toggle():
    stop() if is_running() else start()


def run_daemon():
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = Gio.DBusProxy.new_sync(
        bus, Gio.DBusProxyFlags.NONE, None,
        "org.gnome.Mutter.IdleMonitor",
        "/org/gnome/Mutter/IdleMonitor/Core",
        "org.gnome.Mutter.IdleMonitor", None,
    )

    watch_ids = {"idle": None, "active": None}

    def current_idle_seconds():
        # re-read config each time so GUI changes apply without restarting the service
        return int(load_config().get("idle_seconds", 300))

    def add_idle_watch():
        result = proxy.call_sync(
            "AddIdleWatch", GLib.Variant("(t)", (current_idle_seconds() * 1000,)),
            Gio.DBusCallFlags.NONE, -1, None,
        )
        watch_ids["idle"] = result.unpack()[0]

    def add_active_watch():
        result = proxy.call_sync(
            "AddUserActiveWatch", None, Gio.DBusCallFlags.NONE, -1, None,
        )
        watch_ids["active"] = result.unpack()[0]

    def on_signal(_proxy, _sender, signal_name, params):
        if signal_name != "WatchFired":
            return
        (fired_id,) = params.unpack()
        if fired_id == watch_ids["idle"]:
            start()
            add_active_watch()
        elif fired_id == watch_ids["active"]:
            stop()
            add_idle_watch()

    proxy.connect("g-signal", on_signal)
    add_idle_watch()

    GLib.MainLoop().run()


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
