# GNOME Wayland integration test checklist

These checks exercise behavior that the unit suite cannot reproduce without a real
GNOME Shell, Mutter session, WebKitGTK, and physical or virtual displays. Run them
in a disposable user session where possible. Do not use the lock-failure cases on
a production workstation with unsaved work.

## Record the environment

- [ ] GNOME Shell version: `gnome-shell --version`
- [ ] Session type: `echo "$XDG_SESSION_TYPE"` (must be `wayland` for this checklist)
- [ ] Display count and resolutions from **Settings → Displays**
- [ ] Installed revision and service state:
  ```sh
  git -C /path/to/material-screensaver rev-parse --short HEAD
  systemctl --user status material-screensaver.service
  ```

## Viewer lifecycle

- [ ] Start, stop, and toggle the viewer repeatedly (at least 10 cycles):
  `material-screensaver-ctl.py start`, `stop`, and `toggle`.
- [ ] Confirm each Show produces one fullscreen viewer on every connected monitor.
- [ ] Dismiss with **Super+Q**; confirm windows close and desktop shortcuts/Overview behavior are restored.
- [ ] Restart the user service while the viewer is active; confirm no orphan viewer or WebKit processes remain and a later activation succeeds.
- [ ] Close the viewer during its startup/map delay; confirm a subsequent Show works on the first attempt.
- [ ] Change resolution, scale, and orientation while idle, then activate the viewer again.

## Lock behavior

- [ ] Set a short non-zero **Lock after** timeout. Confirm the session locks and the viewer does not remain over the lock screen.
- [ ] Repeat with **Super+L** while the viewer is active; after unlocking, confirm the viewer does not reappear.
- [ ] Set **Lock after** to 0 and confirm the timer does not lock the session.
- [ ] In a disposable session only, make all lock commands unavailable or force them to return non-zero. Confirm the viewer stays visible and the failure is written to the service journal.
- [ ] In a disposable session only, terminate the viewer process abnormally while a lock timeout is enabled. Confirm the daemon logs the abnormal exit and attempts to lock immediately.
- [ ] Confirm a normal **Super+Q** dismissal does not trigger an unexpected lock.

## Displays and recovery

- [ ] With two monitors connected, confirm both show the selected scene and both windows close on Hide.
- [ ] Disconnect one monitor while the viewer is visible; confirm the daemon recovers without stale windows. Reconnect it and activate again.
- [ ] Repeat with a monitor added before activation and with the primary display changed.
- [ ] Suspend/resume or dock/undock, then confirm the next activation covers the current display layout.
- [ ] Repeat the lifecycle and lock checks after restarting GNOME Shell or logging out and back in.

## Record results

Run the checklist against the exact commit under test. Do not mark an item passed from code inspection alone. Copy this table into the test report and add one row per scenario exercised:

| Test ID / scenario | Result (Pass / Fail / Blocked / Not run) | Environment / display topology | Evidence or safe journal event names | Follow-up issue |
|---|---|---|---|---|
| Example: LOCK-02 | Not run | GNOME version, Wayland, monitor count and scale | Not run | — |

For any display-related failure, record each monitor's resolution and scale factor, primary-monitor choice, and whether the failure followed a hot-plug, docking, rotation, or resolution change. For recovery failures, include the event name and non-sensitive fields such as backend, status, and exception type; never include configured hook commands or private message text.

## Collect diagnostics

After a failure, capture the output before restarting the service:

```sh
journalctl --user -u material-screensaver.service --since "10 minutes ago" --no-pager
systemctl --user status material-screensaver.service --no-pager
pgrep -af 'material-screensaver-ctl.py|WebKit|bwrap'
```

Record the exact steps, GNOME version, display topology, expected result, actual result,
and relevant journal lines. Redact usernames or other private information before
sharing logs. These checks are manual; passing the source-level unit tests does not
establish that live Wayland behavior has passed.
