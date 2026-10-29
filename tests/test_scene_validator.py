"""Regression tests for scene package metadata and asset validation."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-scenes.py"
spec = importlib.util.spec_from_file_location("scene_validator", VALIDATOR)
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)


class TestSceneValidator(unittest.TestCase):
    def test_all_built_in_scenes_validate(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATOR)], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("failed", result.stdout)
        self.assertIn("Validated", result.stdout)

    def test_reports_missing_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            scene = Path(temp) / "broken.html"
            scene.write_text("<html><head></head><body></body></html>", encoding="utf-8")
            errors = validator.validate_scene(scene)
        self.assertIn("missing HTML doctype", errors)
        self.assertIn("missing non-empty <title>", errors)
        self.assertIn("missing viewport metadata", errors)
        self.assertIn("missing Content-Security-Policy metadata", errors)

    def test_reports_missing_local_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            scene = Path(temp) / "broken.html"
            scene.write_text(
                '<!doctype html><html><head><title>Test</title>'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
                '</head><body><img src="missing.png"></body></html>',
                encoding="utf-8",
            )
            errors = validator.validate_scene(scene)
        self.assertIn("missing local asset: missing.png", errors)

    def test_reports_missing_css_url_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            scene = Path(temp) / "broken.html"
            scene.write_text(
                '<!doctype html><html><head><title>Test</title>'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
                '<style>body { background-image: url("missing.png"); }</style>'
                '</head><body></body></html>',
                encoding="utf-8",
            )
            errors = validator.validate_scene(scene)
        self.assertIn("missing local asset: missing.png", errors)

    def test_checks_assets_in_linked_and_imported_stylesheets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            styles = root / "styles"
            styles.mkdir()
            (root / "missing-font.woff2").write_bytes(b"not the referenced asset")
            (styles / "nested.css").write_text(
                '@font-face { src: url("../fonts/missing-font.woff2"); }', encoding="utf-8"
            )
            (styles / "style.css").write_text(
                '@import "nested.css"; body { color: white; }', encoding="utf-8"
            )
            scene = root / "scene.html"
            scene.write_text(
                '<!doctype html><html><head><title>Test</title>'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
                '<link rel="stylesheet" href="styles/style.css"></head><body></body></html>',
                encoding="utf-8",
            )
            errors = validator.validate_scene(scene)
        self.assertIn("missing local asset: ../fonts/missing-font.woff2", errors)

    def test_checks_same_relative_asset_from_each_stylesheet_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            (first / "texture.png").write_bytes(b"present only in first directory")
            (first / "style.css").write_text('body { background: url("texture.png"); }', encoding="utf-8")
            (second / "style.css").write_text('body { background: url("texture.png"); }', encoding="utf-8")
            scene = root / "scene.html"
            scene.write_text(
                '<!doctype html><html><head><title>Test</title>'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
                '<link rel="stylesheet" href="first/style.css">'
                '<link rel="stylesheet" href="second/style.css">'
                '</head><body></body></html>',
                encoding="utf-8",
            )
            errors = validator.validate_scene(scene)
        self.assertIn("missing local asset: texture.png", errors)

    def test_rejects_remote_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            scene = Path(temp) / "remote.html"
            scene.write_text(
                """<!doctype html><html><head><title>Test</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <meta http-equiv="Content-Security-Policy" content="default-src 'none'">
                </head><body><script src="https://example.com/scene.js"></script></body></html>""",
                encoding="utf-8",
            )
            errors = validator.validate_scene(scene)
        self.assertIn("remote asset is not allowed: https://example.com/scene.js", errors)

    def test_rejects_assets_outside_scene_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "secret.png"
            outside.write_bytes(b"test")
            scene_dir = root / "scenes"
            scene_dir.mkdir()
            scene = scene_dir / "escape.html"
            scene.write_text(
                '<!doctype html><html><head><title>Test</title>'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
                f'</head><body><img src="../{outside.name}"></body></html>',
                encoding="utf-8",
            )
            errors = validator.validate_scene(scene)
        self.assertIn("asset escapes scene directory: ../secret.png", errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
