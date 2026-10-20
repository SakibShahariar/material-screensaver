"""Regression tests for idle-watch registration recovery."""
import os
import unittest

import support


class TestIdleWatchRefresh(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_missing_watch_retries_when_timeout_is_unchanged(self):
        self.assertTrue(self.ctl._idle_watch_needs_refresh(300, 300, None))

    def test_registered_watch_does_not_refresh_when_timeout_is_unchanged(self):
        self.assertFalse(self.ctl._idle_watch_needs_refresh(300, 300, 42))

    def test_timeout_change_refreshes_even_when_watch_exists(self):
        self.assertTrue(self.ctl._idle_watch_needs_refresh(600, 300, 42))

    def test_daemon_poll_checks_registration_state(self):
        path = os.path.join(support.REPO_ROOT, "bin", "material-screensaver-ctl.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn(
            '_idle_watch_needs_refresh(current, last_idle_seconds[0], _idle_watch_ids.get("idle"))',
            source,
        )


if __name__ == "__main__":
    unittest.main()
