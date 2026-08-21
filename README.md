# Material Screensaver

A collection of animated, matugen-themed "screensavers" for GNOME (Wayland), plus a
GTK4/libadwaita settings app to manage them.

Since GNOME dropped native animated screensavers, these run as standalone HTML/JS
pages launched fullscreen in a kiosk browser window, triggered automatically after
an idle timeout (via GNOME's `org.gnome.Mutter.IdleMonitor`) or manually via a
keyboard shortcut.

## Styles included

Blob, Flow, Ripple, Orbit, Kaleidoscope, Constellation, Solar System (3D, Three.js),
Lorenz Attractor, Fireworks, Typewriter, Terrain, Vinyl, City, Bubbles, Origami,
Lanterns, Rain, Koi Pond, DNA, Oscilloscope, Sakura, Paper Boats.

All pull their color palette live from a [matugen](https://github.com/InioX/matugen)
generated stylesheet, so they follow your current wallpaper-derived Material You theme.

## Requirements

- GNOME on Wayland (uses `org.gnome.Mutter.IdleMonitor` over D-Bus for idle detection)
- Python 3 with PyGObject (`python3-gi`) — almost always preinstalled on GNOME systems
- A Chromium-family browser (Chromium, Chrome, Brave, Helium) or Firefox
- matugen generating colors to `~/.config/matugen/matugen-colors.css`
  (edit the `<link rel="stylesheet" href="file://...">` path in each `.html` file
  if your matugen output lives somewhere else)
- Solar System specifically needs internet access on first launch (loads Three.js
  from a CDN)

## Install

```bash
./install.sh
```

This places files under `~/.local/bin`, `~/.local/share/material-screensaver/`,
`~/.local/share/icons/`, `~/.config/systemd/user/`, and `~/.local/share/applications/`,
then enables the idle-watching systemd service and opens the settings GUI. The app
also shows up in GNOME's Activities search with its own icon once installed.

## Manage

Run the settings app (search "Material Screensaver Settings" in the app grid, or
`~/.local/bin/material-screensaver-gui.py`) to:

- pick the active screensaver
- set the idle timeout
- toggle 12-hour/24-hour clock format
- pick a specific browser (or leave on auto-detect)
- set a keyboard shortcut to toggle it manually
- enable/disable the automatic idle-triggered daemon
- preview (start/stop) on demand

Adding a new style later is just dropping a new `.html` file into
`~/.local/share/material-screensaver/screensavers/` — it shows up in the picker
automatically.

## Manual control

```bash
material-screensaver-ctl.py start    # force start
material-screensaver-ctl.py stop     # force stop
material-screensaver-ctl.py toggle   # start if not running, stop if running
material-screensaver-ctl.py daemon   # run the idle-watching loop (used by the systemd service)
```
