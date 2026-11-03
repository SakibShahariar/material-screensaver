"""Coverage for the canonical visual descriptions shown in Settings and README."""
import json
import os
from pathlib import Path
import tempfile
import unittest

import support
import material_screensaver_config as config_store


class TestSceneDescriptions(unittest.TestCase):
    def setUp(self):
        self.scene_dir = Path(support.DEFAULT_SAVERS)
        self.metadata_path = self.scene_dir / "scene-descriptions.json"
        self.payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        self.descriptions = self.payload["descriptions"]

    def test_every_builtin_scene_has_one_distinct_visual_description(self):
        scene_files = {path.name for path in self.scene_dir.glob("*.html")}
        self.assertEqual(set(self.descriptions), scene_files)
        self.assertEqual(len(set(self.descriptions.values())), len(scene_files))
        forbidden = ("html", "javascript", "canvas", "webgl", "fps", "controls", "settings")
        for filename, description in self.descriptions.items():
            with self.subTest(scene=filename):
                self.assertTrue(description.strip())
                self.assertLessEqual(len(description), 180)
                lowered = description.lower()
                for term in forbidden:
                    self.assertNotIn(term, lowered)

    def test_loader_rejects_invalid_entries_and_wrong_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scene-descriptions.json"
            path.write_text(json.dumps({
                "version": 1,
                "descriptions": {
                    "valid.html": "A glowing pattern moves across a dark field.",
                    "../outside.html": "Invalid path.",
                    "empty.html": "   ",
                    "wrong.txt": "Not an HTML scene.",
                    "long.html": "x" * 181,
                    "number.html": 42,
                },
            }), encoding="utf-8")
            self.assertEqual(
                config_store.load_scene_descriptions(temp),
                {"valid.html": "A glowing pattern moves across a dark field."},
            )
            path.write_text(json.dumps({"version": 2, "descriptions": {}}), encoding="utf-8")
            self.assertEqual(config_store.load_scene_descriptions(temp), {})

    def test_settings_picker_uses_the_selected_scenes_description(self):
        gui_path = Path(support.REPO_ROOT) / "bin" / "material-screensaver-gui.py"
        source = gui_path.read_text(encoding="utf-8")
        self.assertIn("config_store.load_scene_descriptions(SCREENSAVER_DIR)", source)
        self.assertIn("description = self.scene_descriptions.get(preserve_scene, \"\")", source)
        self.assertIn('self.scene_descriptions.get(self.selected_scene, "")', source)
        self.assertIn("self.combo_row.set_subtitle(subtitle)", source)

    def test_readme_preview_captions_reuse_canonical_descriptions(self):
        readme = (Path(support.REPO_ROOT) / "README.md").read_text(encoding="utf-8")
        for filename in ("blob.html", "origami.html", "city.html", "bubbles.html"):
            with self.subTest(scene=filename):
                self.assertIn(self.descriptions[filename], readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
