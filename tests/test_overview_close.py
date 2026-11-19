"""Coverage for leaving the GNOME Overview before the viewer goes fullscreen."""
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import support


class TestOverviewClose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def _call_with_fake_gi(self, bus):
        fake_gi = types.ModuleType("gi")
        fake_gi.require_version = mock.Mock()
        repo = types.ModuleType("gi.repository")
        repo.Gio = types.SimpleNamespace(
            bus_get_sync=mock.Mock(return_value=bus),
            BusType=types.SimpleNamespace(SESSION=1),
            DBusCallFlags=types.SimpleNamespace(NONE=0),
        )
        repo.GLib = types.SimpleNamespace(
            Variant=lambda signature, value: (signature, value))
        with mock.patch.dict(sys.modules, {"gi": fake_gi, "gi.repository": repo}):
            self.ctl._close_overview_before_show()

    def test_requests_shell_overview_close(self):
        calls = []

        class Bus:
            def call_sync(self, destination, path, interface, method, params, *args, **kwargs):
                calls.append((destination, path, interface, method, params))

        self._call_with_fake_gi(Bus())
        self.assertEqual(len(calls), 1)
        destination, path, interface, method, params = calls[0]
        self.assertEqual(destination, "org.gnome.Shell")
        self.assertEqual(path, "/org/gnome/Shell")
        self.assertEqual(interface, "org.freedesktop.DBus.Properties")
        self.assertEqual(method, "Set")
        self.assertEqual(params, ("(ssv)", (
            "org.gnome.Shell", "OverviewActive", ("b", False),
        )))

    def test_fails_open_when_shell_dbus_is_unavailable(self):
        class Bus:
            def call_sync(self, *args, **kwargs):
                raise RuntimeError("no shell service")

        # Must not raise: activation continues without this optional step.
        self._call_with_fake_gi(Bus())

    def test_show_viewer_closes_overview_before_spawning(self):
        source = (Path(support.REPO_ROOT) / "bin" / "material-screensaver-ctl.py").read_text(
            encoding="utf-8")
        close_at = source.index("        _close_overview_before_show()")
        spawn_at = source.index("            _viewer_process = subprocess.Popen(", close_at)
        self.assertLess(close_at, spawn_at)


if __name__ == "__main__":
    unittest.main(verbosity=2)
