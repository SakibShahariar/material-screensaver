<div align="center">

<img src="icons/material-screensaver-icon.png" width="96" alt="Material Screensaver icon">

# Material Screensaver

**Ambient animated scenes for GNOME on Wayland.**

A lightweight collection of offline HTML/JavaScript screensavers, with a GTK4 and libadwaita settings app.

[Install](#install) · [Features](#features) · [Configure](#configure) · [Troubleshooting](#troubleshooting) · [Contributing scenes](docs/scene-authoring.md)

</div>

## Preview

The built-in scenes combine animated visuals with an optional clock overlay.

| Scene | Scene |
|---|---|
| ![Soft, translucent abstract forms with the clock overlay.](screenshots/shot01.png)<br><sub>Soft, translucent abstract forms with the clock overlay.</sub> | ![A repeating diamond grid in a cool, geometric palette.](screenshots/shot02.png)<br><sub>A repeating diamond grid in a cool, geometric palette.</sub> |
| ![A night skyline with illuminated windows and a clock overlay.](screenshots/shot03.png)<br><sub>A night skyline with illuminated windows and a clock overlay.</sub> | ![A cityscape scene with a subdued night palette.](screenshots/shot04.png)<br><sub>A cityscape scene with a subdued night palette.</sub> |
| ![An additional scene preview from the built-in collection.](screenshots/shot05.png)<br><sub>An additional scene preview from the built-in collection.</sub> | ![Floating, translucent bubbles on a dark background.](screenshots/shot06.png)<br><sub>Floating, translucent bubbles on a dark background.</sub> |
| ![A pixel-style world map made from glowing squares.](screenshots/shot07.png)<br><sub>A pixel-style world map made from glowing squares.</sub> | ![A softly glowing orb framed by a fine border.](screenshots/shot08.png)<br><sub>A softly glowing orb framed by a fine border.</sub> |
| ![An intricate maze-like line pattern in warm colors.](screenshots/shot09.png)<br><sub>An intricate maze-like line pattern in warm colors.</sub> | ![Floating circles, squares, and bars in a warm palette.](screenshots/shot10.png)<br><sub>Floating circles, squares, and bars in a warm palette.</sub> |
| ![Autumn-colored leaves drifting across a dark background.](screenshots/shot11.png)<br><sub>Autumn-colored leaves drifting across a dark background.</sub> | ![Large faceted polygons in a warm, low-contrast palette.](screenshots/shot12.png)<br><sub>Large faceted polygons in a warm, low-contrast palette.</sub> |
| ![A swirling, luminous particle pattern.](screenshots/shot13.png)<br><sub>A swirling, luminous particle pattern.</sub> | ![Small green and blue leaves drifting across a dark background.](screenshots/shot14.png)<br><sub>Small green and blue leaves drifting across a dark background.</sub> |

## Features

- **31 animated scenes** — from space and nature to generative and geometric art.
- **GNOME integration** — launches after idle time and supports multiple monitors.
- **Quick controls** — configurable shortcut; `Super+Q` dismisses the viewer.
- **Settings app** — search, categories, favorites, random selection, per-scene options, and clock overlay.
- **Power controls** — configurable frame-rate cap, optional battery saver, and display blanking.
- **Reduced motion** — honors the system preference and caps requestAnimationFrame-driven scenes at **10 FPS**.
- **Offline by default** — included scenes do not require a network connection.

> **Note:** This is an animated screensaver, not a secure lock screen. Use GNOME's normal session-lock mechanism to lock your computer.

## Requirements

- GNOME on **Wayland**
- Python 3 with PyGObject
- GTK 4, libadwaita, and WebKitGTK 6.0 GI bindings

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

The app lets you choose scenes, set idle and lock timers, configure the FPS cap and battery saver, manage favorites, and adjust clock settings.

Useful commands:

```sh
~/.local/bin/material-screensaver-ctl.py start
~/.local/bin/material-screensaver-ctl.py stop
~/.local/bin/material-screensaver-ctl.py toggle
~/.local/bin/material-screensaver-ctl.py message set "Back at 15:00"
~/.local/bin/material-screensaver-ctl.py message clear
```

To add a scene, place an `.html` file in `~/.local/share/material-screensaver/screensavers/`. See the [scene authoring guide](docs/scene-authoring.md) and [starter template](docs/scene-template.html).

## Troubleshooting

Start with the service status and recent user-service logs. These commands are read-only:

```sh
systemctl --user status material-screensaver.service --no-pager
journalctl --user -u material-screensaver.service --since "10 minutes ago" --no-pager
```

### The service will not start

1. Confirm that you are logged into your GNOME graphical session.
2. Check the status and journal commands above for the first error.
3. After correcting any reported configuration or dependency problem, reload and restart the user service:

   ```sh
   systemctl --user daemon-reload
   systemctl --user restart material-screensaver.service
   ```

### The viewer does not appear

Try starting it manually to separate idle-detection problems from viewer problems:

```sh
~/.local/bin/material-screensaver-ctl.py start
```

If manual start works, check the idle timeout and service logs. If it fails, look for viewer-spawn, WebKitGTK, or scene-loading errors in the journal. The viewer is intended for GNOME on Wayland.

### A stale viewer or WebKit window remains

Ask the application to stop its viewer, then restart the service and check its status:

```sh
~/.local/bin/material-screensaver-ctl.py stop
systemctl --user restart material-screensaver.service
systemctl --user status material-screensaver.service --no-pager
```

If the window remains, collect the recent service logs before attempting manual process cleanup; avoid killing unrelated WebKit processes.

### Lock timer or unlock behavior is unexpected

Check the lock-after value in Settings and review recent service logs for lock-related failures. A lock-after value of `0` disables automatic locking by this application. Material Screensaver is not a lock screen; use GNOME's normal session lock. See [issue #8](https://github.com/SakibShahariar/material-screensaver/issues/8).

### A monitor is clipped, blurry, or missing

Check GNOME display settings and the configured scale factors, then restart the viewer after the display layout is stable. Record the monitor count, resolutions, scale factors, and whether a display was hot-plugged. See [issue #43](https://github.com/SakibShahariar/material-screensaver/issues/43) and the [GNOME Wayland integration test plan](docs/gnome-integration-test-plan.md).

### Sharing useful diagnostic information

For a focused log excerpt, run:

```sh
journalctl --user -u material-screensaver.service --since "10 minutes ago" --no-pager | grep 'event='
```

Include the symptom, steps to reproduce, expected and actual behavior, and relevant error/event names when reporting a problem. Review output before sharing it: redact personal paths, private message text, hook commands, and other sensitive information. See [issue #6](https://github.com/SakibShahariar/material-screensaver/issues/6) for integration testing and [issue #36](https://github.com/SakibShahariar/material-screensaver/issues/36) for lifecycle logging.

## Advanced integrations

Optional lock/unlock hooks can run trusted commands when the session lock state changes. They are disabled by default and use argument arrays rather than shell command strings. Configure `lock_hook` and `unlock_hook` in `~/.config/material-screensaver/config.json`; merge them into the existing file rather than replacing your settings.

For suite integrations, use the control script to show or dismiss the animated viewer. Locking the session is a separate operation and should use GNOME's normal session-lock mechanism.

## Uninstall

From the repository checkout:

```sh
bash uninstall.sh
```

The uninstaller removes the application's service, screensaver files, cache, and companion extension. It also removes the application configuration by default. To preserve your configuration for a future reinstall, use:

```sh
bash uninstall.sh --keep-settings
```

Other GNOME extensions and unrelated user settings are preserved.

## Development

Run automated tests:

```sh
python3 -m unittest discover -s tests -v
```

These checks do not replace live testing in a GNOME Wayland session. See the [integration test plan](docs/gnome-integration-test-plan.md).

## License

GPL-3.0-only. See [LICENSE](LICENSE). Third-party assets and dependencies may have separate notices or licenses.
