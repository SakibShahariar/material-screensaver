# Material Screensaver

<img src="icons/material-screensaver-icon.png" width="96" height="96" alt="Material Screensaver icon">
(SVG version: `icons/material-screensaver-icon.svg`)

A collection of animated, matugen-themed "screensavers" for GNOME (Wayland), plus a
GTK4/libadwaita settings app to manage them.

## Contents

[Styles](#styles-included) · [Requirements](#requirements) · [Install](#install) · [Manage](#manage) · [Manual control](#manual-control) · [Tests](#tests)

Since GNOME dropped native animated screensavers, these run as standalone HTML/JS
pages in a fullscreen `WebKitGTK` (`WebKit 6.0` + `Gtk 4`) window — one per monitor —
with `SessionManager` inhibit and input grab while visible, triggered automatically after
an idle timeout (via GNOME's `org.gnome.Mutter.IdleMonitor`) or manually via a
keyboard shortcut. The only way to dismiss it is **Super+Q** — mouse, keys and clicks
are ignored (interactive styles still respond to them in-page). No external browser,
no PID file.

## Styles included

Solar System, Starfield, N-Body Galaxies, Cymatics, Kaleidoscope, Magnetic Field
Lines, Strange Attractor Flow, Soft-Body Creatures, Blob, Flow, Bounce, Game of Life,
Wave-Function Collapse, Circuit Board, Glitch, Constellation, Voronoi, Origami,
Paper Cranes, Sakura, Lanterns, Rain, Bubbles, City, Autumn Leaves, Fireworks,
Typewriter, Quantum Interference (GLSL/WebGL), Organic Harmonic Field (GLSL/WebGL),
Metaphysical Horizon, Rain on a Window — **31 total**.

All pull their color palette live from a [matugen](https://github.com/InioX/matugen)
generated stylesheet, so they follow your current wallpaper-derived Material You theme.
Shared helpers `screensavers/clock-shared.js` (clock) and `screensavers/theme-shared.js`
(readRGB/rgba) are available for new styles to avoid duplicating theme code.

## Requirements

- GNOME on Wayland (uses `org.gnome.Mutter.IdleMonitor` over D-Bus for idle detection)
- Python 3 with PyGObject (`python3-gi`) and `WebKitGTK 6.0` (`webkitgtk6.0`, `gir1.2-webkit-6.0`) — almost always available on GNOME systems
- matugen generating colors to `~/.config/matugen/matugen-colors.css`
  (edit the `<link rel="stylesheet" href="file://...">` path in each `.html` file
  if your matugen output lives somewhere else)
- No network required — Solar System is now pure Canvas 2D (previous Three.js CDN
  dependency was removed in the v2 rewrite)

## Install

```bash
./install.sh
```

This places files under `~/.local/bin`, `~/.local/share/material-screensaver/`,
`~/.local/share/icons/`, `~/.config/systemd/user/`, and `~/.local/share/applications/`,
then enables the idle-watching systemd service and opens the settings GUI. The app
also shows up in GNOME's Activities search with its own icon once installed.

A companion GNOME Shell extension (`extensions/material-screensaver-gestures@io.github.sakib`)
is installed and enabled as part of this. It stops 3-finger touchpad swipes
(workspace switch / overview / alt-tab) from firing while the screensaver's fullscreen
viewer is focused — it self-guards by window title, so normal desktop gestures are
untouched. Because the shell only discovers extensions at login, **log out and back in
once** after a fresh install for it to take effect.

## Manage

Run the settings app (search "Material Screensaver Settings" in the app grid, or
`~/.local/bin/material-screensaver-gui.py`) to:

- pick the active screensaver
- set the idle timeout
- toggle 12-hour/24-hour clock format
- set a keyboard shortcut to toggle it manually
- enable/disable the automatic idle-triggered daemon

Adding a new style later is just dropping a new `.html` file into
`~/.local/share/material-screensaver/screensavers/` — it shows up in the picker
automatically.

## Manual control

```bash
material-screensaver-ctl.py start    # force start
material-screensaver-ctl.py stop     # force stop
material-screensaver-ctl.py toggle   # show (repeat presses are safe); dismiss with any key / Super+Q / stop
material-screensaver-ctl.py daemon   # run the idle-watching loop (used by the systemd service)
```

## Tests

Run the suite (Python stdlib `unittest` + `node --check` for JS syntax):

```bash
python3 -m unittest discover -s tests -v
```

Checks every `.html` for structure (doctype/viewport/matugen link/CDN), theming
consistency (clock & theme helper usage, valid `rgb(var(--x) / alpha)` CSS),
JS syntax of every inline script and both shared helpers, config parsing edge
cases (malformed JSON, bool/float/non-int rejection, bounds), screensaver
selection (random/fallback/unicode filenames), the screen-lock command
fallback chain (`gdbus` → `loginctl` → `xdg-screensaver`), external-lock
handling, lock *scheduling* (fire-after-timeout, zero/negative disable, cancel,
reschedule dedup, inactive-viewer guard — via a real GLib loop with mocked
side-effects), and install/desktop/systemd packaging. Point it at an installed
copy with `MS_TEST_SCREENSAVERS_DIR=~/.local/share/material-screensaver/screensavers`.

The only untested portion is the live interaction with the GNOME session itself
(actual `Mutter.IdleMonitor` watch registration, the SessionManager inhibit,
and locking a real session), which needs a running desktop.
