"""Tests for the screen-lock path in bin/material-screensaver-ctl.py.

The end-to-end behaviour (viewer visible -> lock_after_seconds -> session
locked -> viewer hidden) needs a live GNOME session + Mutter IdleMonitor, so it
cannot run in CI. What IS testable offline is the lock command fallback chain:
a failing gdbus call (rc!=0, e.g. org.gnome.ScreenSaver absent on modern
GNOME) must fall through to loginctl/xdg-screensaver instead of silently
stopping.
"""
import os
import subprocess as real_subprocess
import unittest

import support


class _Call:
    def __init__(self, argv):
        self.argv = argv


class _Result:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdout = b""
        self.stderr = b""


class TestLockCommandChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def setUp(self):
        self.calls = []
        self.results = []
        self._orig_run = self.ctl.subprocess.run

        def fake_run(cmd, **kwargs):
            self.calls.append(cmd)
            if not self.results:
                return _Result(0)
            r = self.results.pop(0)
            if isinstance(r, Exception):
                raise r
            return _Result(r)

        self.ctl.subprocess.run = fake_run

    def tearDown(self):
        self.ctl.subprocess.run = self._orig_run

    def commands(self):
        return [c[0] for c in self.calls]

    def test_candidate_preference_order(self):
        # gdbus first, then loginctl, then xdg-screensaver
        self.assertEqual(
            self.ctl.LOCK_COMMANDS,
            [
                ["gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
                 "--object-path", "/org/gnome/ScreenSaver",
                 "--method", "org.gnome.ScreenSaver.Lock"],
                ["loginctl", "lock-session"],
                ["xdg-screensaver", "lock"],
            ],
        )

    def test_first_candidate_success_stops_chain(self):
        self._lock(returncodes=[0])
        self.assertEqual(self.commands(), ["gdbus"])

    def test_nonzero_rc_falls_through_to_next_success(self):
        # The regression: gdbus returns rc=1 (service absent); before the fix,
        # loginctl was never attempted because subprocess.run does not raise on
        # a nonzero exit code.
        self._lock(returncodes=[1, 0])
        self.assertEqual(self.commands(), ["gdbus", "loginctl"])

    def test_missing_binary_falls_through(self):
        self._lock(returncodes=[FileNotFoundError(), 0])
        self.assertEqual(self.commands(), ["gdbus", "loginctl"])

    def test_all_fail_silently(self):
        # Must not raise even when every candidate fails.
        self._lock(returncodes=[1, 2, 3])
        self.assertEqual(self.commands(), ["gdbus", "loginctl", "xdg-screensaver"])

    def test_no_candidates_is_noop(self):
        saved = self.ctl.LOCK_COMMANDS
        self.ctl.LOCK_COMMANDS = []
        try:
            self._lock(returncodes=[])  # should not raise, no calls
            self.assertEqual(self.calls, [])
        finally:
            self.ctl.LOCK_COMMANDS = saved

    def _lock(self, returncodes):
        self.results = list(returncodes)
        self.ctl._lock_screen()


class TestExternalLockHandling(unittest.TestCase):
    """org.gnome.ScreenSaver.ActiveChanged(true) while the viewer is up must
    tear the screensaver down — external locks (Super+L, loginctl, GNOME timer)
    would otherwise leave it running after unlock."""

    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def setUp(self):
        self.hidden = 0
        self._orig = {
            "is_viewer_active": self.ctl.is_viewer_active,
            "hide_viewer": self.ctl.hide_viewer,
        }
        self.ctl.is_viewer_active = lambda: self.active
        self.ctl.hide_viewer = lambda: self._bump()

    def _bump(self):
        self.hidden += 1
        self.active = False  # hiding the viewer deactivates it (real hide_viewer does this)

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(self.ctl, name, fn)

    def test_external_lock_hides_viewer(self):
        self.active = True
        self.ctl._on_screen_saver_active_changed(True)
        self.assertEqual(self.hidden, 1)

    def test_unlock_does_not_hide(self):
        self.active = True
        self.ctl._on_screen_saver_active_changed(False)
        self.assertEqual(self.hidden, 0)

    def test_lock_when_inactive_is_noop(self):
        self.active = False
        self.ctl._on_screen_saver_active_changed(True)
        self.assertEqual(self.hidden, 0)

    def test_repeat_active_changed_only_hides_once(self):
        self.active = True
        self.ctl._on_screen_saver_active_changed(True)
        self.assertEqual(self.hidden, 1)
        self.ctl._on_screen_saver_active_changed(True)
        # first hide already deactivated the viewer -> no double hide
        self.assertEqual(self.hidden, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)