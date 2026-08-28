# Material Screensaver

<img src="icons/material-screensaver-icon.png" width="96" height="96" alt="Material Screensaver icon">

A collection of animated, matugen-themed "screensavers" for GNOME (Wayland), plus a
GTK4/libadwaita settings app to manage them.

Since GNOME dropped native animated screensavers, these run as standalone HTML/JS
pages in a fullscreen `WebKitGTK` (`WebKit 6.0` + `Gtk 4`) window — one per monitor —
with `SessionManager` inhibit and input grab while visible, triggered automatically after
an idle timeout (via GNOME's `org.gnome.Mutter.IdleMonitor`) or manually via a
keyboard shortcut. No external browser, no PID file.

## Styles included

Blob, Flow, Ripple, Orbit, Kaleidoscope, Constellation, Solar System (3D, Three.js),
Lorenz Attractor, Fireworks, Fireflies, Typewriter, Terrain, Vinyl, City, Bubbles,
Origami, Lanterns, Rain, Koi Pond, DNA, Oscilloscope, Sakura, Paper Boats, Bounce,
Fractal Zoom (GLSL/WebGL), Falling Sand, Voronoi, Game of Life, Glitch, Organic
Harmonic Field (GLSL/WebGL), Solar Orbit, Aurora Wave, Hyper-Tesseract, Metaphysical
Horizon, Ambient Mesh, Quantum Interference, Starfield, Strange Attractor Flow,
Snow Globe, Lava Lamp, Jellyfish, Spirograph, Circuit Board, Autumn Leaves, Radar,
Paper Cranes (46 total).

All pull their color palette live from a [matugen](https://github.com/InioX/matugen)
generated stylesheet, so they follow your current wallpaper-derived Material You theme.
Shared helpers `screensavers/clock-shared.js` (clock) and `screensavers/theme-shared.js`
(readRGB/rgba) are available for new styles to avoid duplicating theme code.

Note: most files went through a Gemini update pass that reintroduced an invalid CSS
`rgba(var(--x), alpha)` pattern (mixing space-separated variable expansion with a
comma-separated alpha argument — invalid per spec, and the same category of bug that
broke clock text once before). This has been mechanically batch-fixed to valid
`rgb(var(--x) / alpha)` syntax across all affected files. The *new content* those
files gained beyond that fix (new panels, features, effects) has not yet been
individually deep-reviewed the way earlier additions were — only automated syntax
and known-bug-pattern scanning has been done so far.

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

## Manage

Run the settings app (search "Material Screensaver Settings" in the app grid, or
`~/.local/bin/material-screensaver-gui.py`) to:

- pick the active screensaver
- set the idle timeout
- toggle 12-hour/24-hour clock format
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
