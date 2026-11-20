"""Opacity animation helpers for the optional viewer transitions.

Kept separate from the control script so the pure interpolation logic can be
tested without GTK/WebKit, and so other modules can reuse it.
"""
from __future__ import annotations


def opacity_at(start, target, elapsed_ms, duration_ms):
    """Linear opacity interpolation for one animation step."""
    if duration_ms <= 0:
        return target
    fraction = min(1.0, max(0.0, elapsed_ms / float(duration_ms)))
    return start + (target - start) * fraction


def fade_opacity(widget, target, duration_ms=180, on_complete=None, debug=None):
    """Animate a widget's opacity on the GLib main loop; failures are non-fatal."""
    if widget is None:
        if on_complete is not None:
            on_complete()
        return
    try:
        from gi.repository import GLib
        start = widget.get_opacity()
        step_ms = max(16, duration_ms // 8)
        elapsed = [0]

        def tick():
            elapsed[0] += step_ms
            value = opacity_at(start, target, elapsed[0], duration_ms)
            try:
                widget.set_opacity(value)
            except Exception as exc:
                if debug is not None:
                    debug(f"Could not set animated opacity: {exc}")
                return False
            if elapsed[0] >= duration_ms:
                if on_complete is not None:
                    on_complete()
                return False
            return True

        GLib.timeout_add(step_ms, tick)
    except Exception as exc:
        if debug is not None:
            debug(f"Could not animate viewer opacity: {exc}")
        if on_complete is not None:
            on_complete()
