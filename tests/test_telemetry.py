"""Coverage for the local telemetry snapshot passed to viewer scenes."""
from pathlib import Path
import unittest

import support


class TestTelemetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_snapshot_has_sane_local_values(self):
        data = self.ctl._telemetry_snapshot()
        self.assertIsInstance(data["cores"], int)
        self.assertGreaterEqual(data["cores"], 1)
        self.assertIsInstance(data["procs"], int)
        self.assertGreaterEqual(data["procs"], 0)
        self.assertIsInstance(data["load"], float)
        self.assertGreaterEqual(data["load"], 0)
        self.assertIsInstance(data["uptime"], int)
        self.assertGreaterEqual(data["uptime"], 0)

    def test_viewer_receives_telemetry(self):
        source = (Path(support.REPO_ROOT) / "bin" / "material-screensaver-ctl.py").read_text(
            encoding="utf-8")
        self.assertIn('env["MS_TELEMETRY"] = json.dumps(_telemetry_snapshot())', source)
        self.assertIn('uri += "&ms_telem=" + quote(telemetry, safe="")', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
