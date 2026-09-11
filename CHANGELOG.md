# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Removed
- "Test it now" preview group (Start/Stop buttons) from the settings GUI — the inline
  Live Preview thumbnail already shows the selected style.
### Added
- New screensaver styles **Rain on a Window** (Canvas 2D, blob.html-shaped, full clock
  + hint + `prefers-reduced-motion` handling). README "Styles included" list + count
  updated (the test-suite count check parses that line dynamically). Collection total
  is now 31.
- 6 further styles (Dinner Under Wisteria, Steam Train at Night, Lighthouse Beam,
  Cherry Blossom Stream, Forest Fireflies, Subway Platform) were authored, trialed,
  then removed; none kept. README count temporarily rose to 37 then reverted.
- 11 further new styles (Moonlit Surf, Milky Way Ridge, Butterfly Migration, Black
  Hole Disc, Wet Street Neon, Harbor Cranes, Sand Mandala, Frost on Glass, Mycelium
  Pulse, Paper Lantern Parade, Zodiac Sky) were authored, trialed, then removed
  (kept only Rain on a Window). Collection total is now 31.
### Fixed
- Desktop file `Exec=`/`TryExec=` now use `%h/.local/bin/material-screensaver-gui.py` so the
  settings app launches from the app grid even when `~/.local/bin` is absent from `$PATH`
  (regression vs the v2.2.2 changelog claim).
- `_valid_int` (ctl + gui) rejects fractional floats instead of silently truncating
  (`300.9` → `300`) in user-editable config.
- Lock fallback chain: a failing `gdbus`/`org.gnome.ScreenSaver` call (rc≠0) now falls
  through to `loginctl lock-session` / `xdg-screensaver lock`. Previously a nonzero
  `subprocess.run` exit was never detected, so the screen never locked on systems where
  the GNOME ScreenSaver D-Bus service is absent.
- External locks (Super+L, `loginctl lock-session`, GNOME Settings timer) now dismiss the
  screensaver: the daemon subscribes to `org.gnome.ScreenSaver.ActiveChanged` and hides
  the viewer when the session locks, so it no longer keeps running after unlock.
### Changed
- Dismissal is now **Super+Q only**: mouse movement, clicks and ordinary keys no longer
  close the screensaver (interactive styles still receive them in-page for their own use);
  removed the now-meaningless `close_on_mouse` config key and its settings-toggle.
  The daemon no longer arms Mutter's user-active watch, since activity no longer dismisses.
- 3-finger touchpad swipes no longer switch workspace/overview over the screensaver: a
  companion shell extension (`extensions/material-screensaver-gestures@io.github.sakib`)
  consumes `TOUCHPAD_SWIPE` events while the fullscreen viewer is focused (self-guarded
  by window title). Installed + enabled by `install.sh`; takes effect after one re-login.
  Note: `org.gnome.Shell.Eval` is disabled since GNOME 45, so the previous `Shell.Eval`
  overview-hide has been a silent no-op on modern GNOME.
- Live preview stays active when **Random** is enabled (it previews a random style on
  every refresh instead of blanking); clicking the preview loads the next one — a random
  style in random mode.
### Added
- Test suite under `tests/`: JS syntax via `node --check` on every inline script + shared
  helpers, theming consistency (clock/theme helper usage, `rgb(var(--x) / alpha)` CSS lint),
  HTML structure, config-parsing edge cases, screensaver selection, lock command fallback
  chain, lock scheduling (fire/cancel/disable/dedup/inactive-guard via GLib loop),
  external-lock handling, packaging checks.
- CI: consolidated static checks into the suite, added a `tests` job (GI + Node).

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
