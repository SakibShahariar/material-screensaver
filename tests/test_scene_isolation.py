"""The scene URI scheme must serve only files from the screensavers directory."""
import os
import tempfile
import unittest
from pathlib import Path

import support


class FakeContext:
    def __init__(self):
        self.scheme = None
        self.callback = None

    def register_uri_scheme(self, scheme, callback):
        self.scheme = scheme
        self.callback = callback


class FakeRequest:
    def __init__(self, uri):
        self.uri = uri
        self.length = None
        self.content_type = None

    def get_uri(self):
        return self.uri

    def finish(self, stream, length, content_type):
        self.length = length
        self.content_type = content_type

    def finish_error(self, error):
        raise AssertionError("the isolation handler must not use finish_error")


class TestSceneIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def test_scene_uri_uses_allowlisted_scheme(self):
        uri = self.ctl._scene_uri("/tmp/scenes/a.html", "12h", {})
        self.assertTrue(uri.startswith("material-scene://scene/a.html?"), uri)
        self.assertIn("format=12h", uri)
        self.assertNotIn("file://", uri)

    def test_scheme_handler_serves_only_files_inside_scene_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "scenes")
            os.makedirs(root)
            allowed = Path(root, "allowed.txt")
            allowed.write_text("hello", encoding="utf-8")
            outside = Path(temp, "outside.txt")
            outside.write_text("secret", encoding="utf-8")

            ctx = FakeContext()
            self.assertTrue(self.ctl._register_scene_scheme(ctx, root))
            self.assertEqual(ctx.scheme, "material-scene")
            self.assertTrue(callable(ctx.callback))

            good = FakeRequest("material-scene://scene/allowed.txt")
            ctx.callback(good)
            self.assertEqual(good.length, len(b"hello"))
            self.assertEqual(good.content_type, "text/plain")

            # URL-encoded traversal must not escape the allowlisted directory.
            traversal = FakeRequest(
                "material-scene://scene/%2e%2e%2foutside.txt")
            ctx.callback(traversal)
            self.assertEqual(traversal.length, 0, "traversal was served")

            missing = FakeRequest("material-scene://scene/missing.txt")
            ctx.callback(missing)
            self.assertEqual(missing.length, 0, "missing file was served")

    def test_viewer_installs_scheme_before_creating_views(self):
        source = (Path(support.REPO_ROOT) / "bin" / "material-screensaver-ctl.py").read_text(
            encoding="utf-8")
        shared = (Path(support.REPO_ROOT) / "bin" / "material_screensaver_scene_uri.py").read_text(
            encoding="utf-8")
        self.assertIn("_register_scene_scheme(ctx,", source)
        self.assertIn("ctx.register_uri_scheme(SCENE_SCHEME, _on_request)", shared)
        install_at = source.index("_register_scene_scheme(ctx,")
        view_at = source.index("web = WebKit.WebView.new_with_context(ctx)")
        self.assertLess(install_at, view_at)


if __name__ == "__main__":
    unittest.main(verbosity=2)
