"""Logic tests for lock scheduling (_schedule_lock / _cancel_lock).

Running a real GLib main loop with mocked side-effects exercises the actual
timeout bookkeeping: scheduling, zero/negative disable, cancel, reschedule
dedup, and the viewer-active guard — all without a GNOME session.
Skipped when GI/GLib is unavailable.
"""
import unittest
import warnings

import support

warnings.filterwarnings("ignore", category=DeprecationWarning,
                        module="gi.events")


def _glib_ok():
    try:
        import gi
        gi.require_version("GLib", "2.0")
        from gi.repository import GLib  # noqa: F401
        return True
    except Exception:
        return False


@unittest.skipUnless(_glib_ok(), "GI/GLib unavailable; lock-schedule logic tests skipped")
class TestScheduleLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()
        from gi.repository import GLib
        cls.GLib = GLib

        cls._orig = {
            "lock_screen": cls.ctl._lock_screen,
            "hide_viewer": cls.ctl.hide_viewer,
            "is_viewer_active": cls.ctl.is_viewer_active,
            "load_config": cls.ctl.load_config,
        }

    def setUp(self):
        import tempfile
        self.calls = []
        self.viewer_active = True
        self.cfg = {"active": "blob.html", "idle_seconds": 300,
                    "lock_after_seconds": 1, "clock_format": "24h",
                    "random": False}
        self.ctl._lock_screen = lambda: self.calls.append("lock")
        self.ctl.hide_viewer = lambda: self.calls.append("hide")
        self.ctl.is_viewer_active = lambda: self.viewer_active
        self.ctl.load_config = lambda: self.cfg
        self.ctl._lock_timeout_id = None
        self.ctl._cancel_lock()

    def tearDown(self):
        self.ctl._cancel_lock()
        self.ctl._lock_timeout_id = None
        for name, fn in self._orig.items():
            setattr(self.ctl, name, fn)

    def run_for(self, ms):
        """Run the main loop until `ms` milliseconds have passed."""
        loop = self.GLib.MainLoop()
        self.GLib.timeout_add(ms, loop.quit)
        loop.run()

    def test_lock_fires_then_hides_after_timeout(self):
        self.ctl._schedule_lock()
        self.assertIsNotNone(self.ctl._lock_timeout_id, "expected a scheduled timeout")
        self.run_for(2500)
        self.assertIn("lock", self.calls, "_lock_screen not called after lock_after_seconds")
        self.assertIn("hide", self.calls, "viewer not hidden after locking")
        self.assertLess(self.calls.index("lock"), self.calls.index("hide"),
                        "must lock before hiding the viewer")

    def test_zero_disables_lock(self):
        self.cfg["lock_after_seconds"] = 0
        self.ctl._schedule_lock()
        self.assertIsNone(self.ctl._lock_timeout_id, "0 should schedule nothing")
        self.run_for(1500)
        self.assertEqual(self.calls, [], "lock fired despite lock_after_seconds=0")

    def test_negative_disables_lock(self):
        self.cfg["lock_after_seconds"] = -5
        self.ctl._schedule_lock()
        self.assertIsNone(self.ctl._lock_timeout_id)
        self.run_for(1500)
        self.assertEqual(self.calls, [])

    def test_cancel_prevents_lock(self):
        self.ctl._schedule_lock()
        self.ctl._cancel_lock()
        self.assertIsNone(self.ctl._lock_timeout_id)
        self.run_for(2000)
        self.assertEqual(self.calls, [], "lock fired after cancel")

    def test_reschedule_does_not_double_fire(self):
        # Second schedule must remove the first timeout (dedup).
        self.cfg["lock_after_seconds"] = 60
        self.ctl._schedule_lock()
        self.cfg["lock_after_seconds"] = 1
        self.ctl._schedule_lock()
        self.run_for(2500)
        self.assertEqual(self.calls.count("lock"), 1, "lock fired more than once")

    def test_lock_skipped_when_viewer_inactive(self):
        self.viewer_active = False
        self.ctl._schedule_lock()
        self.run_for(2000)
        self.assertEqual(self.calls, [], "locked/hid even though viewer was not active")


if __name__ == "__main__":
    unittest.main(verbosity=2)