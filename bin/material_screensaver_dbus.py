"""Session-bus client helpers for the Material Screensaver daemon."""
from __future__ import annotations


SERVICE_NAME = "io.github.sakib.MaterialScreensaver"
OBJECT_PATH = "/io/github/sakib/MaterialScreensaver"
INTERFACE_NAME = "io.github.sakib.MaterialScreensaver"


def daemon_is_available(service_name=SERVICE_NAME):
    """Return whether the daemon owns its well-known session-bus name."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "NameHasOwner",
            GLib.Variant("(s)", (service_name,)), None, 0, -1, None)
        return bool(result.unpack()[0])
    except Exception:
        return False


def call_daemon(method, service_name=SERVICE_NAME, object_path=OBJECT_PATH,
                interface_name=INTERFACE_NAME):
    """Call a daemon method; return (success, result_or_error)."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus, Gio.DBusProxyFlags.NONE, None,
            service_name, object_path, interface_name, None)
        if method == "IsActive":
            result = proxy.call_sync(
                "IsActive", None, Gio.DBusCallFlags.NONE, -1, None)
            return True, result.unpack()[0]
        proxy.call_sync(method, None, Gio.DBusCallFlags.NONE, -1, None)
        return True, None
    except Exception as exc:
        return False, str(exc)
