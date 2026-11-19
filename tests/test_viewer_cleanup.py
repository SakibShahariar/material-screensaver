"""Coverage for resolving the real WebView during viewer teardown."""
from pathlib import Path
import types
import unittest

import support


class FakeWebView:
    def terminate_web_process(self):
        pass


class TestViewerWebviewResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_stored_webview_wins(self):
        web = FakeWebView()
        window = types.SimpleNamespace(
            _viewer_webview=web,
            get_child=lambda: types.SimpleNamespace(get_child=lambda: None),
        )
        self.assertIs(self.ctl._viewer_webview(window), web)

    def test_webview_inside_overlay_is_found(self):
        web = FakeWebView()
        overlay = types.SimpleNamespace(get_child=lambda: web)
        window = types.SimpleNamespace(get_child=lambda: overlay)
        self.assertIs(self.ctl._viewer_webview(window), web)

    def test_direct_webview_child_is_found(self):
        web = FakeWebView()
        window = types.SimpleNamespace(get_child=lambda: web)
        self.assertIs(self.ctl._viewer_webview(window), web)

    def test_missing_child_returns_none(self):
        window = types.SimpleNamespace(get_child=lambda: None)
        self.assertIsNone(self.ctl._viewer_webview(window))


class TestCleanupWiring(unittest.TestCase):
    def _source(self):
        return (Path(support.REPO_ROOT) / "bin" / "material-screensaver-ctl.py").read_text(
            encoding="utf-8")

    def test_no_get_child_is_treated_as_webview(self):
        source = self._source()
        self.assertNotIn("web = w.get_child()", source)
        self.assertGreaterEqual(source.count("web = _viewer_webview(w)"), 3)

    def test_teardown_unparents_overlay_before_dispose(self):
        source = self._source()
        teardown = source.split("# ensure WebKit processes terminated before exit")[1].split(
            "sys.exit(0)")[0]
        self.assertIn("web.unparent()", teardown)
        self.assertIn("w.set_child(None)", teardown)
        self.assertIn("web.terminate_web_process()", teardown)


if __name__ == "__main__":
    unittest.main(verbosity=2)
