<div align="center">

<img src="icons/material-screensaver-icon.png" width="96" alt="Material Screensaver icon">

# Material Screensaver

**Ambient animated scenes for GNOME on Wayland.**

A lightweight collection of offline HTML/JavaScript screensavers, with a GTK4 and libadwaita settings app.

[Install](#install) · [Features](#features) · [Configure](#configure) · [Contributing scenes](docs/scene-authoring.md)

</div>

## Preview

| Preview 1 | Preview 2 | Preview 3 |
|---|---|---|
| ![Scene preview](screenshots/shot01.png) | ![Scene preview](screenshots/shot02.png) | ![Scene preview](screenshots/shot03.png) |

## Features

- **31 animated scenes** — from space and nature to generative and geometric art.
- **GNOME integration** — launches after idle time and supports multiple monitors.
- **Quick controls** — configurable shortcut; `Super+Q` dismisses the viewer.
- **Settings app** — search, categories, favorites, random selection, per-scene options, and clock overlay.
- **Power controls** — configurable frame-rate cap, optional battery saver, and display blanking.
- **Theme-aware colors** — optional Matugen stylesheet, with fallback colors when it is unavailable.
- **Reduced motion** — honors the system preference by lowering frame-driven animation to 10 FPS.
- **Offline by default** — included scenes do not require a network connection.

> **Note:** This is an animated screensaver, not a secure lock screen. Use GNOME's normal session-lock mechanism to lock your computer.

## Requirements

- GNOME on **Wayland**
- Python 3 with PyGObject
- GTK 4, libadwaita, and WebKitGTK 6.0 GI bindings
- Matugen is optional

Package names differ by distribution. On Debian/Ubuntu, packages commonly include `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, and `gir1.2-webkit-6.0`. On Fedora, install the corresponding GTK4, libadwaita, and WebKitGTK 6.0 Python/GI packages from enabled repositories.

## Install

From the repository checkout:

```sh
./install.sh
```

After installation, log out and back in once so GNOME Shell discovers the companion extension. Open **Material Screensaver Settings** from Activities.

If the installer cannot access your user systemd bus, run this from your graphical session:

```sh
systemctl --user daemon-reload
systemctl --user enable --now material-screensaver.service
```

## Configure

Open **Material Screensaver Settings** from Activities, or run:

```sh
~/.local/bin/material-screensaver-gui.py
```

The app lets you choose scenes, set idle and lock timers, configure the FPS cap and battery saver, manage favorites, and adjust clock and theme settings.

Useful commands:

```sh
~/.local/bin/material-screensaver-ctl.py start
~/.local/bin/material-screensaver-ctl.py stop
~/.local/bin/material-screensaver-ctl.py toggle
~/.local/bin/material-screensaver-ctl.py message set "Back at 15:00"
~/.local/bin/material-screensaver-ctl.py message clear
```

To add a scene, place an `.html` file in `~/.local/share/material-screensaver/screensavers/`. See the [scene authoring guide](docs/scene-authoring.md) and [starter template](docs/scene-template.html).

## Advanced integrations

Optional lock/unlock hooks can run trusted commands when the session lock state changes. They are disabled by default and use argument arrays rather than shell command strings. Configure `lock_hook` and `unlock_hook` in `~/.config/material-screensaver/config.json`; merge them into the existing file rather than replacing your settings.

For suite integrations, use the control script to show or dismiss the animated viewer. Locking the session is a separate operation and should use GNOME's normal session-lock mechanism.

## Uninstall

From the repository checkout:

```sh
bash uninstall.sh
```

The uninstaller removes Material Screensaver's service, files, and companion extension while preserving other GNOME extensions and user settings.

## Development

Run automated tests:

```sh
python3 -m unittest discover -s tests -v
```

These checks do not replace live testing in a GNOME Wayland session. See the [integration test plan](docs/gnome-integration-test-plan.md).

## License

GPL-3.0-only. See [LICENSE](LICENSE). Third-party assets and dependencies may have separate notices or licenses.
