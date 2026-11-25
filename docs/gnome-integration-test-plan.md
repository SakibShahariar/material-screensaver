# GNOME Wayland integration test plan

This checklist covers behavior that the unit tests and CI cannot establish without a live GNOME Wayland session. Run it after installing the current checkout with `./install.sh`, logging out and back in, and confirming that the user service is running.

## Record the test environment

Before testing, record:

- Distribution and version
- GNOME Shell version (`gnome-shell --version`)
- Wayland or X11 (`echo "$XDG_SESSION_TYPE"`; this plan targets `wayland`)
- WebKitGTK version/package
- Number of monitors, resolution, scale factor, and whether displays are hot-plugged
- Whether Matugen is installed and whether `~/.config/matugen/matugen-colors.css` exists

Do not describe a case as passed unless it was actually run. Mark it **Blocked** if the required hardware or session is unavailable, and **Not run** otherwise.

## Test matrix

| ID | Scenario | Steps | Expected result |
|---|---|---|---|
| START-01 | Manual start | Run `~/.local/bin/material-screensaver-ctl.py start`. | Viewer appears fullscreen on each connected monitor; no traceback. |
| START-02 | Stop while visible | Run `~/.local/bin/material-screensaver-ctl.py stop`. | All viewer windows close and desktop input returns. |
| START-03 | Toggle idempotency | Run `toggle` repeatedly, including two rapid invocations. | Visibility toggles once per invocation; no duplicate viewer processes/windows. |
| START-04 | No graphical session | From a text-only session, invoke the control command. | It exits cleanly with a useful diagnostic; it does not hang or try to initialize WebKit. |
| IDLE-01 | Idle activation | Set a short idle timeout, enable the user service, stop interacting. | Viewer launches close to the configured timeout. |
| IDLE-02 | Activity before timeout | Move mouse/type before the idle threshold, then wait again. | No early activation; the full idle period is observed again. |
| IDLE-03 | Change timeout while active | Change idle timeout in Settings while the session is active. | The next activation uses the new timeout without restarting the service. |
| IDLE-04 | Invalid/missing idle watch recovery | Restart the service and inspect its journal; repeat after transient D-Bus/service errors if safely reproducible. | A failed watch registration is logged and retried; automatic activation recovers. |
| IDLE-05 | Idle activation from the Overview | Open the GNOME Overview, leave the input idle past the configured timeout, and observe activation. | The Overview closes first, then the viewer covers the screen fullscreen (no thumbnail inside the Overview). With the Shell D-Bus service unavailable, activation still proceeds and the failure is logged. |
| VIEW-01 | Dismiss with shortcut | Show viewer and press Super+Q. | Viewer closes and does not immediately reopen. |
| VIEW-02 | Configured shortcut | Configure a non-conflicting shortcut and invoke it while hidden and visible. | It shows/hides the viewer; Super+Q remains reserved for dismissal. |
| VIEW-03 | Lock from viewer | Set a short lock-after timeout and let it expire. | GNOME locks; the viewer is dismissed/hidden as intended. |
| VIEW-04 | Scene rotation while active | Enable rotation with a short interval, show the viewer, and wait through several switches; then press Super+Q. | Scenes change in order without new viewer processes; the lock timer continues, Super+Q still dismisses, and no WebKit helpers leak. |
| VIEW-05 | Lock countdown indicator | With `lock_countdown=true` and a short lock delay, show the viewer and capture screenshots before and during the final 10 s. Then dismiss during the countdown and wait past the original deadline. | A pill appears at bottom centre for the final 10 s and ticks down to 1 s; lock fires at the deadline; dismissal cancels the pending lock and leaves no countdown callback. |
| VIEW-06 | Scene transitions | With `transitions_enabled=true`, show the viewer, let a rotation tick fire, invoke NextScene, then Hide. Observe the fade sequence (temporary instrumentation of the installed fade helper) and confirm the end states render. | Fade in 180 ms on show; rotation fades out 120 ms → `load_uri()` on the existing WebView → fades in 120 ms; NextScene fades out 150 ms then the new viewer fades in 180 ms; Hide fades out 150 ms. No stale viewer process, and the inhibit is released on teardown. |
| LOCK-01 | External lock while visible | Show viewer, press Super+L, then unlock. | Viewer does not appear over the unlocked desktop. |
| LOCK-02 | External lock while hidden | Hide viewer, lock/unlock the session, then wait. | No stale viewer appears; idle activation still works afterward. |
| LOCK-03 | Lock timer set to zero | Set Lock after to 0, show viewer and wait longer than the normal lock delay. | Session is not automatically locked by this app. |
| LOCK-04 | Lock request failure | In a disposable test session, simulate a failed lock request if safely possible. | Viewer remains visible instead of falsely claiming the session is locked; failure is logged. Restore normal session state afterward. |
| LIFE-01 | Service restart while hidden | Run `systemctl --user restart material-screensaver.service`. | Service returns active and idle activation still works. |
| LIFE-02 | Service restart while visible | Show viewer, restart service, and inspect remaining processes/windows. | No orphaned fullscreen window or stale WebKit process remains; later activation works. |
| LIFE-03 | Rapid start/stop | Repeat start/stop/toggle rapidly several times. | No duplicate windows, stuck input grab, or persistent inhibitor. |
| MON-01 | Two monitors | With two monitors connected, show and dismiss viewer. | Every monitor is covered and all windows close together. |
| MON-02 | Different scale/resolution | Use monitors with different resolutions/scales. | No uncovered strips, incorrectly sized windows, or persistent off-screen windows. |
| MON-03 | Hot-plug display | Connect/disconnect a monitor while viewer is hidden, then show it again. Repeat only if the desktop remains stable while visible. | No crash; subsequent viewer covers the currently connected displays. Record any limitation. |
| SESSION-01 | Suspend/resume | Show viewer, suspend/resume the machine, then dismiss or wait for idle activation. | Session remains usable; no stale viewer, lock loop, or dead service. |
| SESSION-02 | Logout/login | Log out and back in with the service enabled. | Service starts in the new session and automatic activation works. |
| EXT-01 | Gesture extension enabled | Confirm the companion extension is enabled; show viewer and perform both three- and four-finger workspace/overview swipes. | Swipes with 3+ fingers do not expose workspaces or the overview while the viewer is fullscreen; normal two-finger scrolling and post-dismissal gestures still work. |
| EXT-02 | Extension disabled/unavailable | Disable the companion extension in a test session and repeat the gesture. | Document the expected limitation; viewer operation itself should remain stable. Re-enable the extension afterward. |
| EXT-03 | Optional status menu | With `status_menu_enabled=true`, inspect the Shell panel; toggle the viewer, restart the service, and disable the setting again. | Indicator appears only while enabled; menu actions map to the daemon D-Bus API; Start/Stop/Toggle state follows the viewer; service restart is recovered; lock/idle/fullscreen are unaffected. |
| WEB-01 | Local helper assets | Show scenes that load `clock-shared.js` and theme helpers. | Helpers load; clocks update and there are no missing-resource errors. |
| WEB-02 | Matugen palette present | With a valid Matugen stylesheet, inspect several scenes and the Settings preview. | Palette is applied consistently without unrelated local-file access. |
| WEB-03 | Matugen palette absent | Temporarily move the palette file aside, test, then restore it. | Scenes use fallback colors; viewer and preview do not crash. |
| WEB-04 | Local-file isolation | Use a disposable test scene to attempt reading a separate local file, while checking normal relative assets still load. Never use a real secret or sensitive file. | The unrelated file is not readable; required bundled assets still load. Remove the test scene afterward. |
| SCENE-01 | Every bundled scene | Select each installed scene in turn and leave it running for at least 30 seconds. | No blank page, script exception, or severe rendering failure; clock and theme behavior are sensible. |
| SCENE-02 | WebGL fallback | Test the WebGL-based scenes with acceleration available and, if possible, in a software-rendering session. | Scene renders or fails gracefully; no hung fullscreen window. |
| SETTINGS-01 | Config corruption | In a disposable profile, test missing, empty, malformed JSON, non-object JSON, booleans/fractional numbers in integer fields, and out-of-range values. | App/daemon falls back to safe defaults and remains usable. Restore the original config afterward. |
| SETTINGS-02 | Config write failure | In a disposable profile, make the config directory unwritable and change a setting. | Error is surfaced; no partial/corrupt config is left behind. Restore permissions afterward. |
| INSTALL-01 | Upgrade rollback | Test install over an existing installation in a disposable account/profile; simulate a staged replacement failure only if safe. | Existing scenes remain recoverable and temporary staging/backup directories are cleaned up. |
| INSTALL-02 | Uninstall scope | Uninstall in a disposable profile with unrelated GNOME extensions and other config files present. | Only project-owned files and extension UUID are removed; unrelated settings/extensions remain. |

## Logs and evidence

Capture logs around failures with:

```sh
journalctl --user -u material-screensaver.service --since "10 minutes ago" --no-pager
systemctl --user status material-screensaver.service --no-pager
```

Also note the exact steps, expected vs. actual behavior, whether the issue reproduces, and whether the viewer was launched manually or by idle detection. Avoid including personal paths or sensitive data in public issue reports.

The daemon emits lifecycle events prefixed with `[material-screensaver] event=`. To isolate them from the journal:

```sh
journalctl --user -u material-screensaver.service --since "10 minutes ago" --no-pager | grep 'event='
```

For recovery-related failures, preserve the event name and safe metadata such as `backend`, `status`, or `error` type. Useful events include `idle_watch_registration_failed`, `viewer_spawn_failed`, `lock_monitor_failed`, `session_lock_backend_failed`, and `session_lock_failed`. Do not copy configured hook commands or private message text into public reports.

## Observed results (2026-11-20)

These were actually executed in a GNOME Shell 51.1 / Wayland session or an isolated Xvfb display; cases not listed here remain unverified.

| Case | Result | Evidence |
|---|---|---|
| START-01 (manual start) | **Passed**: `start` exited 0, viewer active with one viewer process. | Live D-Bus + process count, 2026-11-20. |
| START-02 (stop while visible) | **Passed**: `stop` exited 0, viewer inactive with no viewer process. | Live D-Bus + process count, 2026-11-20. |
| START-03 (toggle idempotency) | **Passed**: two concurrent `toggle` calls from hidden left the viewer hidden with no duplicate process. | Live D-Bus + process count, 2026-11-20. |
| IDLE-01 (idle activation) | **Passed**: with `idle_seconds=10`, the daemon registered a 10 s watch and the viewer spawned without manual Show. | Journal `idle_watch_registered timeout_seconds='10'` + `viewer_spawned`, 2026-11-20. |
| IDLE-02 (activity before timeout) | **Inconclusive** — needs real physical input. Synthetic `xdotool` mouse moves and key presses through Xwayland did not reset Mutter's idle clock, so the viewer activated anyway. Do not count as passed. | Repeated attempts with 10 s timeout, 2026-11-20. |
| IDLE-05 (Overview) | **Passed**: with the Overview open and `idle_seconds=10`, the viewer activated and the Overview was closed (`OverviewActive` true → false) before/at activation. | D-Bus property before/after + 5 overview-related daemon log lines, 2026-11-20. |
| IDLE-03 (change timeout while active) | **Passed**: changing to 42 s while the viewer was active did not re-register the watch; after Hide the new 42 s watch was registered. | Journal timestamps, 2026-11-20. |
| LOCK-03 (lock timer zero) | **Passed**: with `lock_after_seconds=0`, no `lock_timer_fired` event during an 8 s visible period. | Journal, 2026-11-20. |
| START-04 (no graphical session) | **Passed** with the daemon stopped: `DISPLAY`/`WAYLAND_DISPLAY` unset, `start` exited 1 with `No graphical session available; cannot start screensaver.` With the daemon running, the CLI intentionally delegates the Show to the daemon instead, so this case must be run with the service stopped. | Live command output, 2026-11-20. |
| LIFE-01 (service restart while hidden) | **Passed**: service restarted, new PID active, `idle_watch_registered` emitted by the new daemon, viewer inactive. | `systemctl --user restart` + journal, 2026-11-20. |
| LIFE-02 (service restart while visible) | **Passed**: viewer was active before restart; after restart no viewer process or WebKit helper remained and `IsActive` was false. | Viewer PID before/after and `pgrep` counts, 2026-11-20. The service's cgroup kill cleans up the detached viewer subprocess. |
| LOCK-01 (external lock while visible) | **Passed**: with the viewer active, `loginctl lock-session` produced `session_lock_detected`, hid the viewer, and released the inhibit; no viewer process or WebKit helper remained. After the user unlocked, `session_unlocked` and a fresh idle watch were logged, the viewer did not reappear, and a 10 s idle activation worked again. Original config restored. | Live lock/unlock with journal and D-Bus evidence, 2026-11-20. A harmless GLib child-watch warning (`waitid ... No child processes`) was logged during lock. |
| VIEW-01 (Super+Q) | **Passed** with a real keyboard: the viewer closed and did not reopen after 12 s; no viewer process remained. Note: GNOME Shell's global Super+Q shortcut performed the dismissal (the app did not log `viewer_dismissed`), then the daemon cleaned up via its child watch. Earlier `xdotool`/uinput attempts were false negatives — synthetic input did not reach the native Wayland viewer. | Real key press + D-Bus state and journal, 2026-11-20. |
| WEB-04 (local-file isolation) | **Passing** after the custom `material-scene://` scheme replaced `file://` for scenes and their relative assets. An isolated Xvfb viewer loaded the disposable scene, same-directory CSS and the inline script (confirmed by a same-directory beacon request), while `../secret.js` — which previously executed — was rejected with an empty response, and an absolute `file://` script did not execute. URL-encoded traversal (`%2e%2e%2f`) is rejected by the handler. Real bundled scenes (`analog-clockwork.html`, `solar-system.html`, `organic-harmonic-field.html`) still load their main document, `matugen-colors.css` and `clock-shared.js` through the handler. Deterministic unit tests cover allow/deny decisions; the GUI preview uses the same scheme. | Xvfb viewer logs + unit tests, 2026-11-26. Previous result (2026-11-20) was a genuine failure with WebKit's file-access settings. |
| SCENE-01 (bundled scenes) | **Partial**: all 31 bundled scenes were rendered for ~2 s each under Xvfb; no `scene_load_failed` events, crashes, or early exits, and no leftover WebKit processes. The full case (30 s per scene, live GNOME, visual inspection) was not run. | Automated smoke run over all 31 scenes, 2026-11-20. |
| LIFE-03 (rapid start/stop) | **Passed** for cleanup: 8 consecutive Show/Hide cycles via the daemon D-Bus; 56 newly spawned viewer/WebKit/bwrap processes, 0 remained after any Hide. | Recorded on issue #60 along with a before/after procfs-read and latency comparison on a ~500-process desktop. |
| VIEW-04 (rotation) | **Passing**: with `rotation_interval_seconds=30` and `lock_after_seconds=45`, rotation armed across 45 scenes and ticked at +30 s while the D-Bus `Activity` method was called every 2 s. The fixed deadline fired at +45 s (`lock_timer_fired` → `session_lock_attempted` → `session_lock_succeeded backend='loginctl'`) with 30+ `lock_deadline_kept` events and no reset — the gap that was previously unverified. The daemon hid the viewer and released the inhibit on lock. With locking disabled, three consecutive 30 s ticks kept the process count flat at 8 total (6 WebKit+bwrap) across the first three ticks, then stepped once to 10 after the fourth scene loaded — no unbounded growth. Real Super+Q under rotation was not re-tested (synthetic input does not reach the native Wayland viewer); the earlier real-key VIEW-01 result still applies. | Live GNOME 51.1/Wayland journal, D-Bus and process sampling, 2026-11-22 (v2.4.1). |
| VIEW-05 (lock countdown) | **Passing**: with `lock_after_seconds=25` and `lock_countdown=true`, screenshots showed no pill at t+2 s, "Locking in 10 seconds" at t+17 s and "Locking in 2 seconds" at t+24 s; `lock_timer_fired` at 25 s. In a second run (`lock_after_seconds=15`), hiding the viewer at t+7 s during the countdown produced no `lock_timer_fired` after 29 s, viewer inactive and idle watch re-armed. Since v2.4.1 the countdown is a fixed deadline and is not re-armed by activity. | Live GNOME 51.1/Wayland screenshots, D-Bus and journal, 2026-11-25 (v2.4.1). |
| VIEW-06 (scene transitions) | **Passing**: temporary instrumentation of the installed fade helper logged the full opacity sequence. Show faded 0.000→1.000 over 180 ms; the 30 s rotation tick faded 1.000→0.000 (120 ms), logged `viewer_rotated`, then 0.000→1.000 (120 ms) on the existing WebView; NextScene faded out over 150 ms, released the inhibit and re-acquired it for the new viewer, which faded in over 180 ms; Hide faded out over 150 ms and released the inhibit. End-state screenshots showed correctly rendered scenes; no viewer/WebKit process remained after Hide. The instrumentation was removed afterward and the installed module is byte-identical to the repo. | Live GNOME 51.1/Wayland journal + screenshots, 2026-11-25 (v2.4.1). Real Super+Q was not re-pressed; earlier VIEW-01 result applies. |
| EXT-03 (status menu) | **Passing with one caveat**: after a Shell restart the extension loaded ACTIVE with no JS error (1.4 (5) at final validation; the earlier 1.3 (4) run verified the timeout fix). The indicator icon was changed from `media-watch-symbolic` to `preferences-desktop-screensaver-symbolic` after visual review; a screenshot confirmed the crescent-moon icon now matches the filled style of neighbouring top-bar icons. The indicator was visible in the top bar only while `status_menu_enabled=true` (AT-SPI: present when on, removed when off), exposed the five menu items, and its Toggle label tracked the viewer: Start → Stop → Start across Show/Hide and Toggle calls, proving the 2 s state-sync poll works. A service restart while visible was recovered — extension stayed ACTIVE, the label matched the new state, and the daemon D-Bus API remained usable. With the menu enabled, the viewer still reached fullscreen and the 10 s lock deadline fired (`lock_timer_fired` → `session_lock_detected` → `session_lock_succeeded backend='loginctl'`); Hide re-armed the idle watch. Caveat: opening the menu and clicking its items could not be driven from this session — XTest and uinput events do not reach the native Wayland Shell, and AT-SPI exposes no activation action on the panel button — so item activation was verified through the exact D-Bus methods they invoke rather than by pointer clicks. | Live GNOME 51.1/Wayland AT-SPI, D-Bus and journal, 2026-11-25 (v2.4.2 candidate). |
| EXT-01 (gesture guard) | **Partial**: extension enabled and ACTIVE in GNOME 51.1, source and tests verified. Physical three-/four-finger swipes were not performed. | Gesture guard blocks 3+ finger swipes in source. |
| Settings window state | **Passed** for size clamp: saved `1520x816` was clamped to `1496x816` against the live monitor geometry. | Issue #57; position restoration is documented as not applicable on GTK4/Wayland. |

## Current verification boundary

Passing CI establishes that the repository's configured static checks and automated tests passed. It does **not** establish that Mutter idle watches, GNOME locking, real fullscreen coverage, touchpad gesture interception, WebKit file isolation, suspend/resume, or monitor hot-plug behavior passed. Those require this live-session checklist and must be recorded separately.
