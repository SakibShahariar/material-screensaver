import json
from pathlib import Path
import tempfile
import unittest

import support
from material_scene_manifest import validate_manifest
import material_screensaver_config as config_store


class TestSceneManifest(unittest.TestCase):
    def test_builtin_manifest_is_valid_and_covers_html_scenes(self):
        entries, errors = validate_manifest(support.DEFAULT_SAVERS)
        self.assertEqual(errors, [])
        self.assertIsNotNone(entries)
        self.assertEqual(
            set(entries),
            {path.name for path in Path(support.DEFAULT_SAVERS).glob("*.html")},
        )

    def test_invalid_manifest_disables_runtime_scene_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "valid.html").write_text("<!doctype html>", encoding="utf-8")
            (root / "scene-manifest.json").write_text(json.dumps({
                "version": 1,
                "scenes": {"valid.html": {"description": "ok", "capabilities": ["Canvas"]}},
            }), encoding="utf-8")
            entries, errors = validate_manifest(root)
            self.assertIsNone(entries)
            self.assertTrue(errors)
            self.assertEqual(config_store.list_screensavers(root), [])

    def test_invalid_scene_is_excluded_but_valid_scene_remains_available(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("good.html", "bad.html"):
                (root / name).write_text("<!doctype html>", encoding="utf-8")
            (root / "scene-manifest.json").write_text(json.dumps({
                "version": 1,
                "scenes": {
                    "good.html": {"description": "ok", "capabilities": []},
                    "bad.html": {"description": "bad", "capabilities": ["Not valid"]},
                },
            }), encoding="utf-8")
            entries, errors = validate_manifest(root)
            self.assertEqual(set(entries or {}), {"good.html"})
            self.assertTrue(errors)
            self.assertEqual(config_store.list_screensavers(root), [str(root / "good.html")])

    def test_legacy_directory_without_manifest_remains_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "custom.html").write_text("<!doctype html>", encoding="utf-8")
            self.assertEqual(config_store.list_screensavers(root), [str(root / "custom.html")])


if __name__ == "__main__":
    unittest.main()
