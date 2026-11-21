# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.4.1] - 2026-11-21
### Fixed
- `lock_after_seconds` is now a fixed deadline from viewer activation: mouse/keyboard
  activity and Mutter's user-active watch no longer restart it. Previously any input
  pushed the timer back, so an active session could run for hours without ever locking.
  The countdown overlay no longer resets on input either, keeping it consistent.

## [2.4.0] - 2026-11-21
### Added
- Fourteen new scenes, taking the collection from 31 to 45: **Aurora Veil**, **Koi Pond**,
  **Constellation Clock**, **Turing Garden** (reaction–diffusion), **Analog Clockwork**
  (mechanical dial), **Julia Bloom** (GPU fractal), **L-system Bloom** (recursive growth),
  **Word Tide** (kinetic typography), **Ink and Light** (themed high-contrast ink),
  **Harmonograph** (mathematical curves), **Topographic Contours**, **Moiré Field**,
  **Wave Interference** and **Prism Field**. All follow the shared Matugen palette, clock
  helper and reduced-motion conventions. The Settings scene picker now sorts by displayed
  name rather than filename.
- **Rain on a Window** — Canvas 2D droplets on glass with clock and reduced-motion handling.
- Optional top-bar status menu with Start / Stop / Toggle / Next Scene / Open Settings
  controls, provided by the companion Shell extension and gated by `status_menu_enabled`
  (off by default, needs a re-login). Next Scene uses the new daemon `NextScene` D-Bus
  method and `next` CLI command, and disables Random each time so the chosen scene shows.
- Optional scene rotation while the screensaver is active (off by default), with an
  interval in Settings. It cycles through favorites when set, otherwise all valid scenes,
  by reloading the existing WebViews — no new processes.
- Optional subtle fade-in/fade-out transitions (off by default, 150–180 ms).
### Changed
- Opacity animation, scene-selection and D-Bus client helpers moved into
  `material_screensaver_transitions.py`, `material_screensaver_scene.py` and
  `material_screensaver_dbus.py` (first slices of the `ctl.py` module split); no behavior change.
- WebKit no longer grants universal access from file URLs; local access remains for sibling
  helpers and the Matugen stylesheet. A narrower resource-loading mechanism is still needed
  to fully isolate user-added scenes (known limitation, tracked on #6).
- Inhibit/Uninhibit failures are logged under `MS_DEBUG` instead of being swallowed.
- Dismissal is **Super+Q only**; mouse movement, clicks and ordinary keys no longer close
  the viewer. The `close_on_mouse` config key and its toggle were removed.
- The companion extension consumes touchpad swipes with three or more fingers while the
  viewer is fullscreen, so 4-finger workspace/overview swipes cannot reveal the desktop.
  `org.gnome.Shell.Eval` is disabled on GNOME 45+, so the old overview-hide was a no-op.
- Live preview stays active under **Random**, previewing a style on each refresh; clicking
  it loads another random style. The "Test it now" Start/Stop buttons were removed.
### Fixed
- The configured lock timer now actually fires while the screensaver runs: Mutter's
  user-active watch was cancelling it during fullscreen focus transitions; those events now
  restart the delay instead. The lock countdown also re-arms after activity.
- Idle activation closes an open GNOME Overview before showing the viewer via the Shell's
  `OverviewActive` D-Bus property, so the viewer covers the screen instead of appearing as
  a thumbnail inside the Overview.
- Viewer teardown resolves the WebView inside its `Gtk.Overlay`, so WebKit is actually
  stopped and disposed without the GTK parent/child critical.
- External locks (Super+L, `loginctl`, GNOME timer) dismiss the viewer and no longer leave
  it running under the lock screen; lock commands fall through on failure and an abnormal
  viewer exit triggers a lock attempt when configured.
- The daemon uses GLib child-watch for the isolated viewer instead of 500 ms polling.
- Desktop entry expands `$HOME` itself (`Exec=` does not support systemd's `%h`); icon
  install uses the hicolor theme and refreshes caches.
- `_valid_int` rejects fractional floats rather than truncating them.
- Gesture guard, config validation, scene validation and settings window size clamping are
  covered by the expanded test suite and CI checks.

## [2.2.2] - 2026-08-30
### Fixed
- Desktop launcher currently uses `sh -c` to expand `$HOME` in `Exec=`; it does not define `TryExec`.
- Icon install places the PNG under the hicolor theme (`48x48/apps`) and runs a proper `gtk-update-icon-cache`.
- Removed dead `_show_cursor_temporarily` body and its call sites (cursor is permanently hidden for non-interactive styles; solar-system manages its own).
- Dropped leftover `"browser": "auto"` config key (Chromium backend removed in v2.0).
- After `lock_after_seconds` fires, the screensaver is now closed (previously it stayed running under the lock screen).
- README style count corrected to 53; Solar System description updated to Canvas 2D.
### Changed
- CI: install real GI/WebKit deps + shellcheck, add import smoke test, systemd unit checks, stricter HTML sanity (CDN detection, shared-helper presence).
- `install.sh`: safer `find`-based chmod, atomic copy via `cp -a .../.`, dual icon locations.

## [2.2.1] - 2026-08-28
### Fixed
- Cursor hidden from first paint — previous `Gdk` blank on `win`+`web` overridden by WebKit CSS, so arrow showed until motion. Now injects `* { cursor: none !important; }` via `WebKit.UserStyleSheet` before `load_uri` + `Gdk` blank (`1×1` transparent `Pixbuf→Texture`) + `JS` `cursor='none'` with robust Wayland schedule (`idle` + `50/200/600/1200ms` + `realize`/`map`, `100/500ms` fullscreen retries) — `bin/material-screensaver-ctl.py:287,350`.
- Cursor `hide except solar-system` — `is_interactive = "solar-system" in basename`; blanket hide and never show on motion for 45 non-interactive styles, `solar-system.html` keeps its own `body.show-cursor` `crosshair`/`pointer` `2.2s` logic `screensavers/solar-system.html:25` — `bin/material-screensaver-ctl.py:287,350,384`.

## [2.2.0] - 2026-08-28
### Fixed
- **Super never opens overview while screensaver visible** — `Gio.Settings` sync primary (`org.gnome.mutter overlay-key=''`) + `gsettings`/`dconf` fallback, verification `verify=''`, re-assert while showing (guard + `180ms` poll), restore exact saved `Gio` value, `CAPTURE` + `key-released` consumes `Super_L/R`, `start()`/`toggle()` inhibit before create — `bin/material-screensaver-ctl.py:592,659,782,290` — verified `Show → '' / Hide → 'Super'` — `37ace77`.
### Added
- Cursor hidden until mouse move `1.2s` show via blank `Gdk.Cursor` on `win`+`web` — `e817929`.

## [2.1.0] - 2026-08-28
### Fixed
- Ghost window not visible but dash/`btop` shows — thorough `WebKit` cleanup (`terminate_web_process`, `run_dispose`, `clear_cache`, `WebsiteDataManager`) `bin/material-screensaver-ctl.py:920`.
- Second `Show` ghosts and not closable on mouse — orphan `bwrap`/`WebKitNetworkProcess` kill + single ephemeral `WebContext` reuse `bin/material-screensaver-ctl.py:135`.
- `Super` alone no longer opens overview (`overlay-key` inhibit/restore, `dconf` fallback, `Shell.Eval hide`) `bin/material-screensaver-ctl.py:592`.
- Only `Super+Q` closes (key `Gdk.KEY_q` + `SUPER_MASK`, consumes `Super_L/R`) `bin/material-screensaver-ctl.py:290`.
### Added
- Lock after 5 min on screensaver (`lock_after_seconds`, `GUI`, `loginctl`/`ScreenSaver.Lock` fallback) `bin/material-screensaver-ctl.py:560,gui.py:128`.
- Option to not close on mouse (`close_on_mouse`, `GUI` switch, `IdleMonitor` active/idle watch guard) `bin/material-screensaver-ctl.py:830,gui.py:135`.
### Changed
- Pre-release hardening: `atexit`/`SIGTERM` overlay restore, single ephemeral leak fix (`30M/cycle`), double-Show mutex `_is_showing`, `GLib` source tracking `_pending_sources`, atomic `save_config` `tmp+rename+fsync`, `systemd` `RestartSec=3` `TimeoutStopSec=5`, atomic `install.sh` dir replace.

## [2.0.0] - 2026-08-28
### Changed
- **BREAKING:** Backend `Chromium`/`Firefox` kiosk → in-process `WebKitGTK 6.0` + `Gtk4` per-monitor fullscreen `bin/material-screensaver-ctl.py:180`. Removes `CHROMIUM_LIKE`/`BROWSER_ORDER`/`PROFILE_ROOT`/`PID` file, adds `SessionManager` inhibit `flags 8`, `D-Bus` `io.github.sakib.MaterialScreensaver` delegation, `WebKit.WebView` `file://?format=`.
- GUI: remove Browser picker `bin/material-screensaver-gui.py:80`.
- CI: `py_compile`, `bash -n`, `desktop-file-validate`, `rgba(var` lint ` .github/workflows/ci.yml:1`.

## [1.0.0] - 2026-08-28
### Added
- 46 matugen screensavers `screensavers:1` (Gemini v2 rewrite): Blob, Flow, Ripple, Orbit, Kaleidoscope, Constellation, Solar System (canvas 2D), Lorenz, Fireworks, Fireflies, Typewriter, Terrain, Vinyl, City, Bubbles, Origami, Lanterns, Rain, Koi, DNA, Oscilloscope, Sakura, Paper Boats, Bounce, Fractal Zoom, Falling Sand, Voronoi, Game of Life, Glitch, Organic Harmonic Field, Solar Orbit, Aurora Wave, Hyper-Tesseract, Metaphysical Horizon, Ambient Mesh, Quantum Interference, Starfield, Strange Attractor Flow, Snow Globe, Lava Lamp, Jellyfish, Spirograph, Circuit Board, Autumn Leaves, Radar, Paper Cranes.
- Helpers `screensavers/clock-shared.js` / `theme-shared.js`, `matugen-colors.css` linkage.
- Random mode `random` `bin/material-screensaver-ctl.py:32,gui.py:94`, `12h/24h` clock `clock_format`.
- Hardening: desktop portability, `shutil.which`, daemon `RemoveWatch` leak fix, stale PID cleanup, atomic `install.sh`, CI workflow.

[2.2.2]: https://github.com/SakibShahariar/material-screensaver/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/SakibShahariar/material-screensaver/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/SakibShahariar/material-screensaver/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/SakibShahariar/material-screensaver/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/SakibShahariar/material-screensaver/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/SakibShahariar/material-screensaver/releases/tag/v1.0.0
