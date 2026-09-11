import Clutter from "gi://Clutter";
import { Extension } from "resource:///org/gnome/shell/extensions/extension.js";

const VIEWER_TITLE = "Material Screensaver";

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

            // Only block 3-finger swipes (workspace switch / overview / alt-tab).
            if (fingers !== 3)
                return Clutter.EVENT_PROPAGATE;

            // Scope to the screensaver: block only while our fullscreen viewer
            // is focused, so nothing changes outside it.
            const win = global.display.get_focus_window();
            if (win && win.is_fullscreen() && win.get_title() === VIEWER_TITLE)
                return Clutter.EVENT_STOP;

            return Clutter.EVENT_PROPAGATE;
        };
        this._eventHandlerId = global.stage.connect('captured-event', this._onEvent);
    }

    disable() {
        if (this._eventHandlerId) {
            global.stage.disconnect(this._eventHandlerId);
            this._eventHandlerId = null;
        }
    }
}