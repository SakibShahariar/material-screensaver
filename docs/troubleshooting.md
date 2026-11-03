# Troubleshooting and advanced configuration

## Service diagnostics

Check the user service and its recent logs:

```sh
systemctl --user status material-screensaver.service --no-pager
journalctl --user -u material-screensaver.service --since "10 minutes ago" --no-pager
```

### The service will not start

1. Confirm that you are logged into your GNOME graphical session.
2. Check the service status and journal for the first error.
3. After correcting the reported configuration or dependency problem, reload and restart the service:

   ```sh
   systemctl --user daemon-reload
   systemctl --user restart material-screensaver.service
   ```

If the installer could not access your user systemd bus, run the reload command above and then:

```sh
systemctl --user enable --now material-screensaver.service
```

### The viewer does not appear

Start it manually to separate idle-detection problems from viewer problems:

```sh
~/.local/bin/material-screensaver-ctl.py start
```

If manual start works, check the idle timeout and service logs. If it fails, look for viewer-spawn, WebKitGTK, or scene-loading errors. The viewer is intended for GNOME on Wayland.

### A stale viewer or WebKit window remains

Ask the application to stop its viewer, then restart the service:

```sh
~/.local/bin/material-screensaver-ctl.py stop
systemctl --user restart material-screensaver.service
systemctl --user status material-screensaver.service --no-pager
```

If the window remains, collect recent service logs before attempting manual process cleanup. Avoid killing unrelated WebKit processes.

### Lock timer or unlock behavior is unexpected

Check the lock-after value in Settings and review recent service logs for lock-related failures. A lock-after value of `0` disables automatic locking by this application. Material Screensaver is not a lock screen; use GNOME's normal session lock. See [issue #8](https://github.com/SakibShahariar/material-screensaver/issues/8).

### A monitor is clipped, blurry, or missing

Check GNOME display settings and the configured scale factors, then restart the viewer after the display layout is stable. Record the monitor count, resolutions, scale factors, and whether a display was hot-plugged. See [issue #43](https://github.com/SakibShahariar/material-screensaver/issues/43) and the [GNOME Wayland integration test plan](gnome-integration-test-plan.md).

## Fullscreen media and idle inhibition

When GNOME applications request session idle inhibition (commonly while fullscreen media is playing), Material Screensaver checks GNOME SessionManager before opening its viewer. If an idle inhibitor is active, activation is deferred and the idle watch is re-armed shortly afterward. If SessionManager is unavailable, the check fails open so ordinary idle activation continues rather than being disabled accidentally.

This depends on GNOME reporting the application's idle inhibitor through the session bus; the app does not infer whether a window is playing video.

## Advanced integrations

Optional lock/unlock hooks can run trusted commands when the session lock state changes. They are disabled by default and use argument arrays rather than shell command strings. Configure `lock_hook` and `unlock_hook` in `~/.config/material-screensaver/config.json`; merge them into the existing file rather than replacing your settings.

For suite integrations, use the control script to show or dismiss the animated viewer. Locking the session is a separate operation and should use GNOME's normal session-lock mechanism.

## Sharing diagnostic information

For a focused log excerpt:

```sh
journalctl --user -u material-screensaver.service --since "10 minutes ago" --no-pager | grep 'event='
```

Before sharing output, review and redact personal paths, private message text, hook commands, and other sensitive information. Include the symptom, reproduction steps, expected and actual behavior, and relevant error/event names. See [issue #6](https://github.com/SakibShahariar/material-screensaver/issues/6) for integration testing and [issue #36](https://github.com/SakibShahariar/material-screensaver/issues/36) for lifecycle logging.
