import Clutter from "gi://Clutter";
import Gio from "gi://Gio";
import GLib from "gi://GLib";
import St from "gi://St";
import * as Main from "resource:///org/gnome/shell/ui/main.js";
import * as PanelMenu from "resource:///org/gnome/shell/ui/panelMenu.js";
import * as PopupMenu from "resource:///org/gnome/shell/ui/popupMenu.js";
import { Extension } from "resource:///org/gnome/shell/extensions/extension.js";

const VIEWER_TITLE = "Material Screensaver";
const SERVICE_NAME = "io.github.sakib.MaterialScreensaver";
const SERVICE_PATH = "/io/github/sakib/MaterialScreensaver";
const ROLE = "material-screensaver-menu";

export default class MaterialScreensaverGestureGuard extends Extension {
    enable() {
        this._onEvent = (actor, event) => {
            if (event.type() !== Clutter.EventType.TOUCHPAD_SWIPE)
                return Clutter.EVENT_PROPAGATE;

            let fingers;
            try {
                fingers = event.get_touchpad_gesture_finger_count();
            } catch {
                return Clutter.EVENT_PROPAGATE;
            }

            // GNOME Shell handles swipe gestures with 3 or more fingers
            // (workspace switch / overview), so block the whole range.
            if (fingers < 3)
                return Clutter.EVENT_PROPAGATE;

            // Scope to the screensaver: block only while our fullscreen viewer
            // is focused, so nothing changes outside it.
            const win = global.display.get_focus_window();
            if (win && win.is_fullscreen() && win.get_title() === VIEWER_TITLE)
                return Clutter.EVENT_STOP;

            return Clutter.EVENT_PROPAGATE;
        };
        this._eventHandlerId = global.stage.connect('captured-event', this._onEvent);

        this._proxy = null;
        this._indicator = null;
        this._pollId = null;
        this._configMonitor = null;
        this._nameWatch = Gio.bus_watch_name(
            Gio.BusType.SESSION, SERVICE_NAME, Gio.BusNameWatcherFlags.NONE,
            () => this._connectProxy(), () => { this._proxy = null; });
        this._connectProxy();

        this._configPath = GLib.build_filenamev([
            GLib.get_home_dir(), ".config", "material-screensaver", "config.json"]);
        try {
            this._configMonitor = Gio.File.new_for_path(this._configPath)
                .monitor(Gio.FileMonitorFlags.NONE, null);
            this._configMonitor.connect("changed", () => this._syncIndicator());
        } catch (e) {
            // Missing config file simply means the indicator stays hidden.
        }
        this._syncIndicator();
    }

    _connectProxy() {
        try {
            this._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, null,
                SERVICE_NAME, SERVICE_PATH, SERVICE_NAME, null);
        } catch (e) {
            this._proxy = null;
        }
        this._syncState();
    }

    _statusMenuEnabled() {
        try {
            const [ok, contents] = Gio.File.new_for_path(this._configPath).load_contents(null);
            if (!ok)
                return false;
            const cfg = JSON.parse(new TextDecoder().decode(contents));
            return cfg.status_menu_enabled === true;
        } catch (e) {
            return false;
        }
    }

    _call(method) {
        if (!this._proxy)
            return;
        try {
            this._proxy.call_sync(method, null, Gio.DBusCallFlags.NONE, 2000, null);
        } catch (e) {
            log(`material-screensaver: ${method} failed: ${e}`);
        }
        this._syncState();
    }

    _syncState() {
        if (!this._indicator || !this._items)
            return;
        let active = false;
        if (this._proxy) {
            try {
                const result = this._proxy.call_sync(
                    "IsActive", null, Gio.DBusCallFlags.NONE, 2000, null);
                active = !!result.deepUnpack()[0];
            } catch (e) {
                active = false;
            }
        }
        this._items.start.setSensitive(!active);
        this._items.stop.setSensitive(active);
        this._items.toggle.label.text = active ? "Stop" : "Start";
    }

    _createIndicator() {
        if (this._indicator)
            return;
        const indicator = new PanelMenu.Button(0.0, "Material Screensaver", false);
        const icon = new St.Icon({
            icon_name: "media-watch-symbolic",
            style_class: "system-status-icon",
        });
        indicator.add_child(icon);

        const items = {
            start: new PopupMenu.PopupMenuItem("Start"),
            stop: new PopupMenu.PopupMenuItem("Stop"),
            toggle: new PopupMenu.PopupMenuItem("Toggle"),
            settings: new PopupMenu.PopupMenuItem("Open Settings"),
        };
        items.start.connect("activate", () => this._call("Show"));
        items.stop.connect("activate", () => this._call("Hide"));
        items.toggle.connect("activate", () => this._call("Toggle"));
        items.settings.connect("activate", () => {
            const app = Gio.DesktopAppInfo.new("material-screensaver-settings.desktop");
            if (app)
                app.launch(null, null);
        });
        for (const item of Object.values(items))
            indicator.menu.addMenuItem(item);

        Main.panel.addToStatusArea(ROLE, indicator);
        this._indicator = indicator;
        this._items = items;
        this._pollId = GLib.timeout_add_seconds(2, () => {
            this._syncState();
            return true;
        });
        this._syncState();
    }

    _removeIndicator() {
        if (this._pollId !== null) {
            GLib.source_remove(this._pollId);
            this._pollId = null;
        }
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
            this._items = null;
        }
    }

    _syncIndicator() {
        if (this._statusMenuEnabled())
            this._createIndicator();
        else
            this._removeIndicator();
    }

    disable() {
        if (this._eventHandlerId) {
            global.stage.disconnect(this._eventHandlerId);
            this._eventHandlerId = null;
        }
        this._removeIndicator();
        if (this._configMonitor) {
            this._configMonitor.cancel();
            this._configMonitor = null;
        }
        if (this._nameWatch) {
            Gio.bus_unwatch_name(this._nameWatch);
            this._nameWatch = null;
        }
        this._proxy = null;
        this._onEvent = null;
    }
}
