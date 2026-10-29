#!/usr/bin/env python3
"""Validate required metadata and local assets in HTML scene packages.

Usage: python3 scripts/validate-scenes.py [SCENE_DIRECTORY]
The default directory is the repository's built-in screensavers/ folder.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import sys


class SceneParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_depth = 0
        self.title = ""
        self.has_html = False
        self.has_head = False
        self.has_body = False
        self.has_viewport = False
        self.has_csp = False
        self.assets: list[str] = []
        self.css_sources: list[str] = []
        self.style_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if attrs_map.get("style"):
            self.css_sources.append(attrs_map["style"] or "")
        if tag == "style":
            self.style_depth += 1
        if tag == "html":
            self.has_html = True
        elif tag == "head":
            self.has_head = True
        elif tag == "body":
            self.has_body = True
        elif tag == "title":
            self.title_depth += 1
        elif tag == "meta":
            name = (attrs_map.get("name") or "").lower()
            http_equiv = (attrs_map.get("http-equiv") or "").lower()
            if name == "viewport":
                self.has_viewport = True
            if http_equiv == "content-security-policy":
                self.has_csp = True
        elif tag in ("script", "img", "audio", "video", "source"):
            value = attrs_map.get("src")
            if value:
                self.assets.append(value)
        elif tag in ("link", "iframe"):
            value = attrs_map.get("href") if tag == "link" else attrs_map.get("src")
            if value:
                self.assets.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        elif tag == "style" and self.style_depth:
            self.style_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.title_depth:
            self.title += data.strip()
        if self.style_depth:
            self.css_sources.append(data)


def validate_scene(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read UTF-8 HTML: {exc}"]

    parser = SceneParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:  # HTMLParser should be tolerant, but report parser failures.
        errors.append(f"cannot parse HTML: {exc}")

    checks = (
        (source.lstrip().lower().startswith("<!doctype html"), "missing HTML doctype"),
        (parser.has_html, "missing <html> element"),
        (parser.has_head, "missing <head> element"),
        (parser.has_body, "missing <body> element"),
        (bool(parser.title.strip()), "missing non-empty <title>"),
        (parser.has_viewport, "missing viewport metadata"),
        (parser.has_csp, "missing Content-Security-Policy metadata"),
    )
    errors.extend(message for passed, message in checks if not passed)

    # Follow CSS dependencies as well as inline CSS. Checking only the
    # stylesheet file misses broken fonts/images and nested @import references.
    import re

    css_url_pattern = re.compile(r"""url\(\s*(["']?)(.*?)\1\s*\)""", re.IGNORECASE)
    css_import_pattern = re.compile(r"""@import\s+(?:url\(\s*)?["']([^"']+)["']\s*\)?""", re.IGNORECASE)
    pending_assets = list(parser.assets)
    for css in parser.css_sources:
        pending_assets.extend(match.group(2).strip() for match in css_url_pattern.finditer(css)
                              if match.group(2).strip())
        pending_assets.extend(match.group(1).strip() for match in css_import_pattern.finditer(css)
                              if match.group(1).strip())
    checked_assets: set[str] = set()
    checked_stylesheets: set[Path] = set()
    scene_root = path.parent.resolve()

    # matugen-colors.css is intentionally generated as a per-user symlink at
    # install time; all other referenced local assets must ship with the scene.
    while pending_assets:
        asset = pending_assets.pop(0).strip()
        if not asset or asset in checked_assets:
            continue
        checked_assets.add(asset)
        if asset.startswith(("http:", "https:", "//")):
            errors.append(f"remote asset is not allowed: {asset}")
            continue
        if asset.startswith(("#", "data:")):
            continue
        asset_path = asset.split("#", 1)[0].split("?", 1)[0]
        if not asset_path or asset_path == "matugen-colors.css":
            continue
        if Path(asset_path).is_absolute():
            errors.append(f"asset must be relative: {asset}")
            continue
        resolved = (path.parent / asset_path).resolve()
        try:
            resolved.relative_to(scene_root)
        except ValueError:
            errors.append(f"asset escapes scene directory: {asset}")
            continue
        if not resolved.is_file():
            errors.append(f"missing local asset: {asset}")
            continue
        if resolved.suffix.lower() == ".css" and resolved not in checked_stylesheets:
            checked_stylesheets.add(resolved)
            try:
                css = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                errors.append(f"cannot read CSS asset {asset}: {exc}")
                continue
            pending_assets.extend(match.group(2).strip() for match in css_url_pattern.finditer(css)
                                  if match.group(2).strip())
            pending_assets.extend(match.group(1).strip() for match in css_import_pattern.finditer(css)
                                  if match.group(1).strip())
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "screensavers",
                        help="directory containing scene HTML files")
    args = parser.parse_args(argv)
    if not args.directory.is_dir():
        print(f"error: not a directory: {args.directory}", file=sys.stderr)
        return 2
    scenes = sorted(args.directory.glob("*.html"))
    if not scenes:
        print(f"error: no .html scenes found in {args.directory}", file=sys.stderr)
        return 2
    failed = 0
    for scene in scenes:
        errors = validate_scene(scene)
        if errors:
            failed += 1
            for error in errors:
                print(f"{scene}: {error}", file=sys.stderr)
        else:
            print(f"OK {scene.name}")
    print(f"Validated {len(scenes)} scene(s): {len(scenes) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
