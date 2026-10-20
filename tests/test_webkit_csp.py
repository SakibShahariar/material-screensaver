"""Headless WebKit regression test for local CSS and CSP restrictions."""
import json
import os
import tempfile
import unittest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gio, GLib, Gtk, WebKit


@unittest.skipUnless(os.environ.get("DISPLAY"), "run under xvfb-run for WebKit integration")
class TestWebKitCSP(unittest.TestCase):
    def test_matugen_stylesheet_loads_and_file_fetch_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            page_dir = os.path.join(temp, "page")
            output_dir = os.path.join(temp, "matugen")
            os.makedirs(page_dir)
            os.makedirs(output_dir)
            css_path = os.path.join(output_dir, "matugen-colors.css")
            with open(css_path, "w", encoding="utf-8") as handle:
                handle.write(":root { --test-palette: #123456; }")
            os.symlink(css_path, os.path.join(page_dir, "matugen-colors.css"))

            csp = (
                "default-src 'none'; base-uri 'none'; form-action 'none'; "
                "object-src 'none'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "font-src 'self' data:; media-src 'self' data:; connect-src 'none';"
            )
            html_path = os.path.join(page_dir, "scene.html")
            with open(html_path, "w", encoding="utf-8") as handle:
                handle.write(
                    '<!doctype html><html><head><meta charset="utf-8">'
                    f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
                    '<link rel="stylesheet" href="matugen-colors.css">'
                    '<style>:root { --fallback-palette: #abcdef; }</style>'
                    '</head><body><script>'
                    'window.fileFetchResult = "pending";'
                    'fetch("file:///etc/passwd").then('
                    '() => { window.fileFetchResult = "allowed"; },'
                    '() => { window.fileFetchResult = "blocked"; });'
                    '</script></body></html>'
                )

            Gtk.init()
            view = WebKit.WebView()
            settings = view.get_settings()
            settings.set_allow_file_access_from_file_urls(False)
            settings.set_allow_universal_access_from_file_urls(False)
            window = Gtk.Window()
            window.set_default_size(320, 200)
            window.set_child(view)
            loop = GLib.MainLoop()
            result = {}
            finished = {"value": False}

            def timeout():
                if not finished["value"]:
                    result["timeout"] = True
                    loop.quit()
                return GLib.SOURCE_REMOVE

            def read_values():
                script = (
                    'JSON.stringify({'
                    'palette: getComputedStyle(document.documentElement)'
                    '.getPropertyValue("--test-palette").trim(),'
                    'fallback: getComputedStyle(document.documentElement)'
                    '.getPropertyValue("--fallback-palette").trim(),'
                    'fetch: window.fileFetchResult'
                    '})'
                )
                view.evaluate_javascript(script, -1, None, None, None, on_evaluated, None)
                return GLib.SOURCE_REMOVE

            def on_evaluated(web_view, js_result, _user_data):
                try:
                    value = web_view.evaluate_javascript_finish(js_result)
                    result.update(json.loads(value.to_string()))
                    if result.get("fetch") == "pending":
                        GLib.timeout_add(100, read_values)
                        return
                except Exception as exc:
                    result["error"] = str(exc)
                finished["value"] = True
                loop.quit()

            def on_load_changed(_view, event):
                if event == WebKit.LoadEvent.FINISHED:
                    GLib.timeout_add(100, read_values)

            view.connect("load-changed", on_load_changed)
            window.present()
            view.load_uri(Gio.File.new_for_path(html_path).get_uri())
            GLib.timeout_add_seconds(8, timeout)
            try:
                loop.run()
            finally:
                window.destroy()

            self.assertFalse(result.get("timeout"), "WebKit did not finish evaluating the local page")
            self.assertNotIn("error", result, result.get("error"))
            self.assertEqual(result.get("palette"), "#123456", "Matugen CSS was blocked by the CSP")
            self.assertEqual(result.get("fallback"), "#abcdef", "inline fallback CSS was blocked by the CSP")
            self.assertEqual(result.get("fetch"), "blocked", "CSP allowed a local-file fetch")


if __name__ == "__main__":
    unittest.main()
