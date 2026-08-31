# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.2] - 2026-08-30
### Fixed
- Desktop file `Exec=` now uses `%h/.local/bin/...` + `TryExec` so the settings app launches reliably even when `~/.local/bin` is not in `$PATH`.
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
