"""Coverage for the extracted D-Bus client helper module (#35)."""
from pathlib import Path
import unittest

import support
from material_screensaver_dbus import (
    INTERFACE_NAME, OBJECT_PATH, SERVICE_NAME, call_daemon, daemon_is_available,
)


class TestDbusClient(unittest.TestCase):
    def test_constants_match_the_daemon_service(self):
        self.assertEqual(SERVICE_NAME, "io.github.sakib.MaterialScreensaver")
        self.assertEqual(OBJECT_PATH, "/io/github/sakib/MaterialScreensaver")
        self.assertEqual(INTERFACE_NAME, SERVICE_NAME)

    def test_missing_service_reports_unavailable(self):
        missing = "io.github.sakib.NoSuchScreensaverService"
        self.assertFalse(daemon_is_available(missing))
        success, error = call_daemon("IsActive", missing)
        self.assertFalse(success)
        self.assertIsInstance(error, str)


class TestDbusClientWiring(unittest.TestCase):
    def test_ctl_uses_shared_helpers(self):
        source = (Path(support.REPO_ROOT) / "bin" / "material-screensaver-ctl.py").read_text(
            encoding="utf-8")
        self.assertIn("import material_screensaver_dbus as dbus_client", source)
        self.assertIn("SERVICE_NAME = dbus_client.SERVICE_NAME", source)
        self.assertIn("return dbus_client.daemon_is_available(SERVICE_NAME)", source)
        self.assertIn("return dbus_client.call_daemon(", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
