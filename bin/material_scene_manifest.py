"""Validation and loading for optional versioned scene manifests."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


MANIFEST_NAME = "scene-manifest.json"
MANIFEST_VERSION = 1
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_-]*$")
_OPTION_TYPES = {"boolean", "integer", "number", "string"}


def _relative_file(root: Path, value: str) -> Path | None:
    if not value or os.path.isabs(value):
        return None
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _validate_option(name: str, spec: object, scene: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(spec, dict):
        return [f"scene {scene!r} option {name!r} must be an object"]
    option_type = spec.get("type")
    if option_type not in _OPTION_TYPES:
        errors.append(f"scene {scene!r} option {name!r} has invalid type")
        return errors
    for key in ("min", "max", "step"):
        if key in spec and (isinstance(spec[key], bool) or not isinstance(spec[key], (int, float))):
            errors.append(f"scene {scene!r} option {name!r}.{key} must be numeric")
    if "min" in spec and "max" in spec and spec["min"] > spec["max"]:
        errors.append(f"scene {scene!r} option {name!r} has min greater than max")
    if "step" in spec and spec["step"] <= 0:
        errors.append(f"scene {scene!r} option {name!r}.step must be positive")
    if "default" in spec:
        value = spec["default"]
        valid = (
            (option_type == "boolean" and isinstance(value, bool))
            or (option_type == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (option_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
            or (option_type == "string" and isinstance(value, str))
        )
        if not valid:
            errors.append(f"scene {scene!r} option {name!r}.default does not match its type")
    return errors


def validate_manifest(directory: str | Path) -> tuple[dict[str, dict] | None, list[str]]:
    """Return manifest entries and precise errors; absent manifests are valid legacy packages."""
    root = Path(directory)
    path = root / MANIFEST_NAME
    if not path.exists():
        return None, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [f"{MANIFEST_NAME}: cannot read JSON: {exc}"]
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("version") != MANIFEST_VERSION:
        return None, [f"{MANIFEST_NAME}: expected version {MANIFEST_VERSION}"]
    scenes = payload.get("scenes")
    if not isinstance(scenes, dict) or not scenes:
        return None, [f"{MANIFEST_NAME}: scenes must be a non-empty object"]
    entries: dict[str, dict] = {}
    html_names = {item.name for item in root.glob("*.html")}
    for filename, raw in scenes.items():
        prefix = f"{MANIFEST_NAME}: scene {filename!r}"
        if not isinstance(filename, str) or os.path.basename(filename) != filename or not filename.endswith(".html"):
            errors.append(f"{prefix} must be a plain .html filename")
            continue
        scene_error_start = len(errors)
        if filename not in html_names:
            errors.append(f"{prefix} has no matching HTML entry point")
        if not isinstance(raw, dict):
            errors.append(f"{prefix} metadata must be an object")
            continue
        description = raw.get("description")
        if description is not None and (not isinstance(description, str) or not description.strip() or len(description.strip()) > 180):
            errors.append(f"{prefix} description must be a non-empty string of at most 180 characters")
        thumbnail = raw.get("thumbnail")
        if thumbnail is not None and (not isinstance(thumbnail, str) or _relative_file(root, thumbnail) is None):
            errors.append(f"{prefix} thumbnail must reference an existing local file")
        capabilities = raw.get("capabilities", [])
        if not isinstance(capabilities, list) or any(not isinstance(item, str) or not _CAPABILITY.fullmatch(item) for item in capabilities):
            errors.append(f"{prefix} capabilities must contain lowercase identifiers")
        elif len(capabilities) != len(set(capabilities)):
            errors.append(f"{prefix} capabilities must not contain duplicates")
        options = raw.get("options", {})
        if not isinstance(options, dict):
            errors.append(f"{prefix} options must be an object")
        else:
            for name, spec in options.items():
                if not isinstance(name, str) or not name or not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                    errors.append(f"{prefix} has an invalid option name")
                else:
                    errors.extend(_validate_option(name, spec, filename))
        if len(errors) == scene_error_start and filename in html_names:
            entries[filename] = raw
    missing = html_names - set(scenes)
    errors.extend(f"{MANIFEST_NAME}: missing metadata for scene {name!r}" for name in sorted(missing))
    return (entries or None), errors
